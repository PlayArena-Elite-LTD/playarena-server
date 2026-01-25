"""
Test suite for payment gateway webhook handlers.
"""

from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.utils import timezone
from decimal import Decimal
import json
import hmac
import hashlib

from wallet.models import Wallet, Deposit, Withdrawal, Transaction
from django.conf import settings

User = get_user_model()


class WebhookTestCase(TestCase):
    """Test webhook handlers"""
    
    def setUp(self):
        """Create test user and wallet"""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.wallet = self.user.wallet
        self.wallet.balance = Decimal('1000.00')
        self.wallet.save()
        self.client = Client()
    
    def _generate_paystack_signature(self, body, secret_key):
        """Generate Paystack webhook signature for testing"""
        return hmac.new(
            secret_key.encode('utf-8'),
            body,
            hashlib.sha512
        ).hexdigest()
    
    def test_paystack_webhook_invalid_signature(self):
        """Test Paystack webhook rejects invalid signature"""
        response = self.client.post(
            '/wallet/webhooks/paystack/',
            data=json.dumps({'event': 'charge.success', 'data': {}}),
            content_type='application/json',
            HTTP_X_PAYSTACK_SIGNATURE='invalid_signature'
        )
        
        self.assertEqual(response.status_code, 401)
        data = json.loads(response.content)
        self.assertEqual(data['status'], 'error')
    
    def test_paystack_webhook_missing_event(self):
        """Test Paystack webhook handles missing event"""
        # Set a test secret key
        original_secret = getattr(settings, 'PAYSTACK_SECRET_KEY', None)
        settings.PAYSTACK_SECRET_KEY = 'test_secret_key'
        
        body = json.dumps({'data': {}}).encode('utf-8')
        signature = self._generate_paystack_signature(body, 'test_secret_key')
        
        response = self.client.post(
            '/wallet/webhooks/paystack/',
            data=body,
            content_type='application/json',
            HTTP_X_PAYSTACK_SIGNATURE=signature
        )
        
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.content)
        self.assertEqual(data['status'], 'error')
        
        # Restore original secret
        if original_secret:
            settings.PAYSTACK_SECRET_KEY = original_secret
    
    def test_paystack_deposit_webhook_success(self):
        """Test Paystack deposit success webhook"""
        # Create a deposit
        deposit = Deposit.objects.create(
            user=self.user,
            amount=Decimal('100.00'),
            payment_method='STRIPE',
            status='PENDING',
            transaction_id='TXN_12345',
            wallet=self.wallet
        )
        
        initial_balance = self.wallet.balance
        
        # Set a test secret key
        original_secret = getattr(settings, 'PAYSTACK_SECRET_KEY', None)
        settings.PAYSTACK_SECRET_KEY = 'test_secret_key'
        
        # Prepare webhook payload
        payload = {
            'event': 'charge.success',
            'data': {
                'reference': 'TXN_12345',
                'status': 'success',
                'amount': 10000  # Amount in kobo
            }
        }
        
        body = json.dumps(payload).encode('utf-8')
        signature = self._generate_paystack_signature(body, 'test_secret_key')
        
        # Send webhook
        response = self.client.post(
            '/wallet/webhooks/paystack/',
            data=body,
            content_type='application/json',
            HTTP_X_PAYSTACK_SIGNATURE=signature
        )
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data['status'], 'ok')
        
        # Verify deposit was completed
        deposit.refresh_from_db()
        self.assertEqual(deposit.status, 'COMPLETED')
        
        # Verify wallet balance was updated
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, initial_balance + deposit.amount)
        
        # Verify transaction was created
        transaction = Transaction.objects.filter(
            wallet=self.wallet,
            transaction_type='DEPOSIT'
        ).first()
        self.assertIsNotNone(transaction)
        self.assertEqual(transaction.amount, deposit.amount)
        
        # Restore original secret
        if original_secret:
            settings.PAYSTACK_SECRET_KEY = original_secret
    
    def test_paystack_withdrawal_webhook_success(self):
        """Test Paystack withdrawal success webhook"""
        # Create a withdrawal
        withdrawal = Withdrawal.objects.create(
            user=self.user,
            amount=Decimal('100.00'),
            payment_method='BANK_TRANSFER',
            account_details='1234567890|001',
            status='PROCESSING',
            transaction_id='TXN_67890',
            wallet=self.wallet
        )
        
        initial_balance = self.wallet.balance
        
        # Set a test secret key
        original_secret = getattr(settings, 'PAYSTACK_SECRET_KEY', None)
        settings.PAYSTACK_SECRET_KEY = 'test_secret_key'
        
        # Prepare webhook payload
        payload = {
            'event': 'transfer.success',
            'data': {
                'transfer_code': 'TXN_67890',
                'reference': 'TXN_67890',
                'status': 'success'
            }
        }
        
        body = json.dumps(payload).encode('utf-8')
        signature = self._generate_paystack_signature(body, 'test_secret_key')
        
        # Send webhook
        response = self.client.post(
            '/wallet/webhooks/paystack/',
            data=body,
            content_type='application/json',
            HTTP_X_PAYSTACK_SIGNATURE=signature
        )
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data['status'], 'ok')
        
        # Verify withdrawal was completed
        withdrawal.refresh_from_db()
        self.assertEqual(withdrawal.status, 'COMPLETED')
        
        # Restore original secret
        if original_secret:
            settings.PAYSTACK_SECRET_KEY = original_secret
    
    def test_paystack_webhook_idempotency(self):
        """Test webhook idempotency (don't process twice)"""
        # Create a completed deposit
        deposit = Deposit.objects.create(
            user=self.user,
            amount=Decimal('100.00'),
            payment_method='STRIPE',
            status='COMPLETED',
            transaction_id='TXN_12345',
            wallet=self.wallet
        )
        
        initial_balance = self.wallet.balance
        
        # Set a test secret key
        original_secret = getattr(settings, 'PAYSTACK_SECRET_KEY', None)
        settings.PAYSTACK_SECRET_KEY = 'test_secret_key'
        
        # Prepare webhook payload
        payload = {
            'event': 'charge.success',
            'data': {
                'reference': 'TXN_12345',
                'status': 'success'
            }
        }
        
        body = json.dumps(payload).encode('utf-8')
        signature = self._generate_paystack_signature(body, 'test_secret_key')
        
        # Send webhook
        response = self.client.post(
            '/wallet/webhooks/paystack/',
            data=body,
            content_type='application/json',
            HTTP_X_PAYSTACK_SIGNATURE=signature
        )
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data['status'], 'ok')
        self.assertEqual(data['message'], 'Already processed')
        
        # Verify balance was not changed
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, initial_balance)
        
        # Restore original secret
        if original_secret:
            settings.PAYSTACK_SECRET_KEY = original_secret

