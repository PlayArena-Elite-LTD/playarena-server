"""
Unit tests for payment gateway security features

Tests verify that all security mitigations are properly implemented.
"""

from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.utils import timezone
from decimal import Decimal
import json
import hmac
import hashlib

from wallet.models import Wallet, Deposit, Transaction
from wallet.paystack_service import PaystackService
from wallet.flutterwave_service import FlutterwaveService
from wallet.utils import complete_deposit_and_credit_wallet
from wallet.error_handlers import (
    sanitize_error_message, validate_payment_amount,
    PaymentValidationError, PaymentSecurityError
)

User = get_user_model()


class PaymentSecurityTests(TestCase):
    """Test security features of payment system"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.wallet = Wallet.objects.create(user=self.user, balance=Decimal('100.00'))
        self.client = Client()
        self.client.force_login(self.user)
    
    def test_api_keys_not_in_code(self):
        """Test that API keys are loaded from environment, not hardcoded"""
        from django.conf import settings
        
        # Check that keys are loaded from config (empty string if not set)
        self.assertIsInstance(settings.PAYSTACK_SECRET_KEY, str)
        self.assertIsInstance(settings.FLUTTERWAVE_SECRET_KEY, str)
        
        # In test environment, keys should be empty or test keys
        # This ensures no production keys are hardcoded
        if settings.PAYSTACK_SECRET_KEY:
            self.assertNotIn('sk_live_', settings.PAYSTACK_SECRET_KEY.lower())
    
    def test_webhook_signature_verification_paystack(self):
        """Test Paystack webhook signature verification"""
        service = PaystackService()
        
        # Valid signature
        payload = '{"event":"charge.success","data":{"reference":"test123"}}'
        secret = 'test_secret'
        signature = hmac.new(
            secret.encode('utf-8'),
            payload.encode('utf-8'),
            hashlib.sha512
        ).hexdigest()
        
        # Mock webhook secret
        from django.conf import settings
        original_secret = settings.PAYSTACK_WEBHOOK_SECRET
        settings.PAYSTACK_WEBHOOK_SECRET = secret
        
        is_valid = service.verify_webhook(payload, signature)
        self.assertTrue(is_valid)
        
        # Invalid signature
        is_valid = service.verify_webhook(payload, 'invalid_signature')
        self.assertFalse(is_valid)
        
        settings.PAYSTACK_WEBHOOK_SECRET = original_secret
    
    def test_webhook_signature_verification_flutterwave(self):
        """Test Flutterwave webhook signature verification"""
        service = FlutterwaveService()
        
        # Valid signature
        payload = '{"event":"charge.completed","data":{"tx_ref":"test123"}}'
        secret = 'test_secret'
        signature = hmac.new(
            secret.encode('utf-8'),
            payload.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        # Mock webhook secret
        from django.conf import settings
        original_secret = settings.FLUTTERWAVE_WEBHOOK_SECRET
        settings.FLUTTERWAVE_WEBHOOK_SECRET = secret
        
        is_valid = service.verify_webhook(payload, signature)
        self.assertTrue(is_valid)
        
        # Invalid signature
        is_valid = service.verify_webhook(payload, 'invalid_signature')
        self.assertFalse(is_valid)
        
        settings.FLUTTERWAVE_WEBHOOK_SECRET = original_secret
    
    def test_duplicate_payment_prevention(self):
        """Test that duplicate payments are prevented"""
        # Create deposit with payment reference
        deposit1 = Deposit.objects.create(
            user=self.user,
            amount=Decimal('50.00'),
            payment_method='PAYSTACK',
            payment_reference='unique_ref_123',
            status='PENDING',
            wallet=self.wallet
        )
        
        # Try to create another deposit with same reference
        with self.assertRaises(Exception):  # Should raise IntegrityError
            deposit2 = Deposit.objects.create(
                user=self.user,
                amount=Decimal('50.00'),
                payment_method='PAYSTACK',
                payment_reference='unique_ref_123',  # Duplicate
                status='PENDING',
                wallet=self.wallet
            )
    
    def test_idempotent_wallet_credit(self):
        """Test that wallet credit is idempotent (won't credit twice)"""
        deposit = Deposit.objects.create(
            user=self.user,
            amount=Decimal('25.00'),
            payment_method='PAYSTACK',
            payment_reference='test_ref_456',
            status='PENDING',
            wallet=self.wallet
        )
        
        initial_balance = self.wallet.balance
        
        # First credit
        result1 = complete_deposit_and_credit_wallet(deposit)
        self.assertTrue(result1['success'])
        self.assertTrue(result1['wallet_credited'])
        
        self.wallet.refresh_from_db()
        balance_after_first = self.wallet.balance
        self.assertEqual(balance_after_first, initial_balance + Decimal('25.00'))
        
        # Second credit attempt (should be idempotent)
        deposit.refresh_from_db()
        result2 = complete_deposit_and_credit_wallet(deposit)
        self.assertTrue(result2['success'])
        # Should detect already credited
        self.assertFalse(result2['wallet_credited'])  # Or already credited
        
        self.wallet.refresh_from_db()
        balance_after_second = self.wallet.balance
        # Balance should not increase again
        self.assertEqual(balance_after_second, balance_after_first)
    
    def test_amount_validation(self):
        """Test payment amount validation"""
        # Valid amount
        amount = validate_payment_amount(Decimal('50.00'))
        self.assertEqual(amount, Decimal('50.00'))
        
        # Amount too low
        with self.assertRaises(PaymentValidationError):
            validate_payment_amount(Decimal('0.50'))
        
        # Amount too high
        with self.assertRaises(PaymentValidationError):
            validate_payment_amount(Decimal('20000.00'))
        
        # Negative amount
        with self.assertRaises(PaymentValidationError):
            validate_payment_amount(Decimal('-10.00'))
    
    def test_error_sanitization(self):
        """Test that error messages are sanitized (no API keys exposed)"""
        error_msg = "Error: API key sk_test_abc123xyz failed"
        sanitized = sanitize_error_message(error_msg)
        
        self.assertNotIn('sk_test_abc123xyz', sanitized)
        self.assertIn('[REDACTED]', sanitized)
    
    def test_user_ownership_verification(self):
        """Test that users can only access their own deposits"""
        # Create another user
        other_user = User.objects.create_user(
            username='otheruser',
            email='other@example.com',
            password='testpass123'
        )
        other_wallet = Wallet.objects.create(user=other_user, balance=Decimal('0.00'))
        
        # Create deposit for other user
        other_deposit = Deposit.objects.create(
            user=other_user,
            amount=Decimal('100.00'),
            payment_method='PAYSTACK',
            status='COMPLETED',
            wallet=other_wallet
        )
        
        # Try to access other user's deposit (should fail)
        response = self.client.get(f'/wallet/payment/success/{other_deposit.id}/')
        self.assertEqual(response.status_code, 404)  # get_object_or_404 returns 404
    
    def test_payment_reference_validation(self):
        """Test that payment references are validated in callbacks"""
        deposit = Deposit.objects.create(
            user=self.user,
            amount=Decimal('30.00'),
            payment_method='PAYSTACK',
            payment_reference='valid_ref_789',
            status='PENDING',
            wallet=self.wallet
        )
        
        # Try callback with wrong reference
        response = self.client.get(
            f'/wallet/payment/success/{deposit.id}/',
            {'reference': 'wrong_ref'}
        )
        # Should redirect to wallet with error (reference mismatch)
        self.assertEqual(response.status_code, 302)
    
    def test_atomic_transaction_rollback(self):
        """Test that failed transactions roll back completely"""
        deposit = Deposit.objects.create(
            user=self.user,
            amount=Decimal('40.00'),
            payment_method='PAYSTACK',
            payment_reference='test_atomic',
            status='PENDING',
            wallet=self.wallet
        )
        
        initial_balance = self.wallet.balance
        initial_transaction_count = Transaction.objects.count()
        
        # Simulate error in credit function (by making deposit invalid)
        deposit.status = 'FAILED'  # This should prevent credit
        deposit.save()
        
        result = complete_deposit_and_credit_wallet(deposit)
        self.assertFalse(result['success'])
        self.assertFalse(result['wallet_credited'])
        
        # Balance should not change
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, initial_balance)
        
        # No transaction should be created
        self.assertEqual(Transaction.objects.count(), initial_transaction_count)
    
    def test_rate_limiting_enforced(self):
        """Test that rate limiting is active on payment endpoints"""
        # Verify rate limiting decorator is applied
        from wallet.views import deposit
        from django_ratelimit.decorators import ratelimit
        # Check if function has rate limiting (decorated)
        self.assertTrue(hasattr(deposit, '__wrapped__') or hasattr(deposit, 'ratelimit_key'))
    
    def test_verification_hash_integrity(self):
        """Test that verification hash prevents tampering"""
        deposit = Deposit.objects.create(
            user=self.user,
            amount=Decimal('60.00'),
            payment_method='PAYSTACK',
            payment_reference='test_hash',
            status='PENDING',
            wallet=self.wallet
        )
        
        # Generate hash
        original_hash = deposit.generate_verification_hash()
        deposit.verification_hash = original_hash
        deposit.save()
        
        # Verify hash
        self.assertTrue(deposit.verify_hash())
        
        # Try to tamper with amount (hash should fail)
        deposit.amount = Decimal('100.00')  # Changed amount
        self.assertFalse(deposit.verify_hash())
    
    def test_suspicious_activity_detection(self):
        """Test suspicious activity detection"""
        from wallet.error_handlers import detect_suspicious_activity
        from django.test import RequestFactory
        
        factory = RequestFactory()
        request = factory.post('/wallet/deposit/')
        request.user = self.user
        request.META['REMOTE_ADDR'] = '192.168.1.1'
        request.META['HTTP_USER_AGENT'] = 'Mozilla/5.0'
        
        deposit = Deposit.objects.create(
            user=self.user,
            amount=Decimal('10.00'),
            payment_method='PAYSTACK',
            status='PENDING',
            wallet=self.wallet,
            ip_address='192.168.1.1'
        )
        
        # Create multiple deposits from same IP (should trigger suspicion)
        for i in range(6):
            Deposit.objects.create(
                user=self.user,
                amount=Decimal('10.00'),
                payment_method='PAYSTACK',
                status='PENDING',
                wallet=self.wallet,
                ip_address='192.168.1.1'
            )
        
        is_suspicious, reasons = detect_suspicious_activity(request, deposit=deposit)
        # Should detect too many deposits
        self.assertTrue(is_suspicious or len(reasons) > 0)


class PaymentIntegrationTests(TestCase):
    """Integration tests for payment flow"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser2',
            email='test2@example.com',
            password='testpass123'
        )
        self.wallet = Wallet.objects.create(user=self.user, balance=Decimal('0.00'))
    
    def test_complete_payment_flow(self):
        """Test complete payment flow: deposit -> credit -> transaction"""
        # Create deposit
        deposit = Deposit.objects.create(
            user=self.user,
            amount=Decimal('75.00'),
            payment_method='PAYSTACK',
            payment_reference='flow_test_123',
            status='PENDING',
            wallet=self.wallet
        )
        
        initial_balance = self.wallet.balance
        initial_transaction_count = Transaction.objects.count()
        
        # Complete deposit and credit wallet
        result = complete_deposit_and_credit_wallet(deposit)
        
        self.assertTrue(result['success'])
        self.assertTrue(result['wallet_credited'])
        self.assertTrue(result['transaction_created'])
        
        # Verify deposit status
        deposit.refresh_from_db()
        self.assertEqual(deposit.status, 'COMPLETED')
        self.assertIsNotNone(deposit.completed_at)
        self.assertIsNotNone(deposit.verification_hash)
        
        # Verify wallet balance
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, initial_balance + Decimal('75.00'))
        
        # Verify transaction created
        self.assertEqual(Transaction.objects.count(), initial_transaction_count + 1)
        transaction = Transaction.objects.latest('created_at')
        self.assertEqual(transaction.amount, Decimal('75.00'))
        self.assertEqual(transaction.transaction_type, 'DEPOSIT')
        self.assertEqual(transaction.wallet, self.wallet)
