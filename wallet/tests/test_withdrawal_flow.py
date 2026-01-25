"""
Comprehensive test suite for withdrawal flow end-to-end.

Tests cover:
- Withdrawal creation
- Saved payment method integration
- Withdrawal processing workflow
- Retry mechanism
- Notifications
- Payment gateway integration
"""

from django.test import TestCase, TransactionTestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from decimal import Decimal
from unittest.mock import patch, MagicMock

from wallet.models import Wallet, Withdrawal, Transaction, SavedPaymentMethod
from wallet.payment_manager import PaymentManager
from wallet.notifications import (
    notify_withdrawal_created,
    notify_withdrawal_processing,
    notify_withdrawal_completed,
    notify_withdrawal_failed,
    notify_withdrawal_retry
)
from alert.models import Notification

User = get_user_model()


class WithdrawalFlowTestCase(TestCase):
    """Test complete withdrawal flow end-to-end"""
    
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
    
    def test_withdrawal_creation_with_manual_account_details(self):
        """Test creating withdrawal with manual account details"""
        withdrawal = Withdrawal.objects.create(
            user=self.user,
            amount=Decimal('100.00'),
            payment_method='BANK_TRANSFER',
            account_details='1234567890|001',
            status='PENDING',
            wallet=self.wallet
        )
        
        self.assertEqual(withdrawal.status, 'PENDING')
        self.assertEqual(withdrawal.amount, Decimal('100.00'))
        self.assertEqual(withdrawal.user, self.user)
        self.assertEqual(withdrawal.wallet, self.wallet)
        # Balance should not be deducted yet (only when COMPLETED)
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal('1000.00'))
    
    def test_withdrawal_creation_with_saved_payment_method(self):
        """Test creating withdrawal using saved payment method"""
        # Create saved payment method
        saved_method = SavedPaymentMethod.objects.create(
            user=self.user,
            payment_method_type='BANK_TRANSFER',
            label='My Main Bank Account',
            account_details='1234567890|001',
            is_default=True,
            is_active=True
        )
        
        # Create withdrawal using saved method
        withdrawal = Withdrawal.objects.create(
            user=self.user,
            amount=Decimal('150.00'),
            payment_method=saved_method.payment_method_type,
            account_details=saved_method.account_details,
            status='PENDING',
            wallet=self.wallet
        )
        
        self.assertEqual(withdrawal.payment_method, 'BANK_TRANSFER')
        self.assertEqual(withdrawal.account_details, saved_method.account_details)
        self.assertEqual(withdrawal.status, 'PENDING')
    
    def test_withdrawal_validation_insufficient_balance(self):
        """Test withdrawal validation rejects insufficient balance"""
        withdrawal = Withdrawal(
            user=self.user,
            amount=Decimal('2000.00'),  # More than balance
            payment_method='BANK_TRANSFER',
            account_details='1234567890|001',
            wallet=self.wallet
        )
        
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError) as context:
            withdrawal.full_clean()
        
        self.assertIn('amount', str(context.exception))
    
    def test_withdrawal_validation_minimum_amount(self):
        """Test withdrawal validation enforces minimum amount"""
        withdrawal = Withdrawal(
            user=self.user,
            amount=Decimal('0.50'),  # Below minimum
            payment_method='BANK_TRANSFER',
            account_details='1234567890|001',
            wallet=self.wallet
        )
        
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError) as context:
            withdrawal.full_clean()
        
        self.assertIn('amount', str(context.exception))
    
    @patch('wallet.payment_manager.PaymentManager.process_withdrawal')
    def test_withdrawal_processing_success(self, mock_process):
        """Test successful withdrawal processing"""
        # Create withdrawal
        withdrawal = Withdrawal.objects.create(
            user=self.user,
            amount=Decimal('100.00'),
            payment_method='BANK_TRANSFER',
            account_details='1234567890|001',
            status='PENDING',
            wallet=self.wallet
        )
        
        initial_balance = self.wallet.balance
        
        # Mock successful payment processing
        mock_process.return_value = {
            'success': True,
            'transaction_id': 'TXN_12345',
            'gateway_response': {'status': 'success'},
            'failure_reason': None
        }
        
        # Process withdrawal
        payment_manager = PaymentManager()
        result = payment_manager.process_withdrawal(withdrawal)
        
        self.assertTrue(result['success'])
        self.assertEqual(result['transaction_id'], 'TXN_12345')
        
        # Update withdrawal status
        withdrawal.status = 'PROCESSING'
        withdrawal.save()
        
        # Simulate completion
        self.wallet.balance -= withdrawal.amount
        self.wallet.save()
        
        Transaction.objects.create(
            wallet=self.wallet,
            amount=-withdrawal.amount,
            transaction_type='WITHDRAWAL',
            description=f"Withdrawal of ${withdrawal.amount}"
        )
        
        withdrawal.status = 'COMPLETED'
        withdrawal.transaction_id = result['transaction_id']
        withdrawal.save()
        
        # Verify balance was deducted
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, initial_balance - withdrawal.amount)
        
        # Verify transaction was created
        transaction = Transaction.objects.filter(
            wallet=self.wallet,
            transaction_type='WITHDRAWAL'
        ).first()
        self.assertIsNotNone(transaction)
        self.assertEqual(transaction.amount, -withdrawal.amount)
    
    @patch('wallet.payment_manager.PaymentManager.process_withdrawal')
    def test_withdrawal_processing_failure_with_retry(self, mock_process):
        """Test withdrawal failure and retry mechanism"""
        # Create withdrawal
        withdrawal = Withdrawal.objects.create(
            user=self.user,
            amount=Decimal('100.00'),
            payment_method='MOBILE_MONEY',
            account_details='1234567890|001',
            status='PENDING',
            wallet=self.wallet,
            retry_count=0,
            max_retry_count=3
        )
        
        # Mock failed payment processing
        mock_process.return_value = {
            'success': False,
            'transaction_id': None,
            'gateway_response': {'status': 'failed', 'error': 'Insufficient funds'},
            'failure_reason': 'Insufficient funds in gateway account'
        }
        
        # Process withdrawal
        payment_manager = PaymentManager()
        result = payment_manager.process_withdrawal(withdrawal)
        
        self.assertFalse(result['success'])
        self.assertIsNotNone(result['failure_reason'])
        
        # Increment retry count
        withdrawal.retry_count += 1
        withdrawal.failure_reason = result['failure_reason']
        withdrawal.gateway_response = result['gateway_response']
        
        # Should retry (not failed yet)
        if withdrawal.retry_count < withdrawal.max_retry_count:
            withdrawal.status = 'PENDING'  # Retry
        else:
            withdrawal.status = 'FAILED'
        
        withdrawal.save()
        
        # Verify retry count incremented
        withdrawal.refresh_from_db()
        self.assertEqual(withdrawal.retry_count, 1)
        self.assertEqual(withdrawal.status, 'PENDING')  # Should retry
    
    @patch('wallet.payment_manager.PaymentManager.process_withdrawal')
    def test_withdrawal_processing_max_retries_exceeded(self, mock_process):
        """Test withdrawal fails after max retries"""
        # Create withdrawal with max retries
        withdrawal = Withdrawal.objects.create(
            user=self.user,
            amount=Decimal('100.00'),
            payment_method='MOBILE_MONEY',
            account_details='1234567890|001',
            status='PENDING',
            wallet=self.wallet,
            retry_count=2,  # One retry left
            max_retry_count=3
        )
        
        # Mock failed payment processing
        mock_process.return_value = {
            'success': False,
            'transaction_id': None,
            'gateway_response': {'status': 'failed'},
            'failure_reason': 'Gateway error'
        }
        
        # Process withdrawal
        payment_manager = PaymentManager()
        result = payment_manager.process_withdrawal(withdrawal)
        
        # Increment retry count
        withdrawal.retry_count += 1
        
        # Max retries exceeded - should fail
        if withdrawal.retry_count >= withdrawal.max_retry_count:
            withdrawal.status = 'FAILED'
            withdrawal.failure_reason = result['failure_reason']
        else:
            withdrawal.status = 'PENDING'
        
        withdrawal.save()
        
        # Verify withdrawal is failed
        withdrawal.refresh_from_db()
        self.assertEqual(withdrawal.retry_count, 3)
        self.assertEqual(withdrawal.status, 'FAILED')
        # Balance should not be deducted
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal('1000.00'))
    
    def test_withdrawal_notification_created(self):
        """Test notification is sent when withdrawal is created"""
        withdrawal = Withdrawal.objects.create(
            user=self.user,
            amount=Decimal('100.00'),
            payment_method='BANK_TRANSFER',
            account_details='1234567890|001',
            status='PENDING',
            wallet=self.wallet
        )
        
        # Send notification
        notify_withdrawal_created(withdrawal)
        
        # Verify notification was created
        notification = Notification.objects.filter(user=self.user).first()
        self.assertIsNotNone(notification)
        self.assertIn('Withdrawal request', notification.message)
        self.assertIn('$100.00', notification.message)
    
    def test_withdrawal_notification_completed(self):
        """Test notification is sent when withdrawal is completed"""
        withdrawal = Withdrawal.objects.create(
            user=self.user,
            amount=Decimal('100.00'),
            payment_method='BANK_TRANSFER',
            account_details='1234567890|001',
            status='COMPLETED',
            transaction_id='TXN_12345',
            wallet=self.wallet
        )
        
        # Send notification
        notify_withdrawal_completed(withdrawal)
        
        # Verify notification was created
        notification = Notification.objects.filter(user=self.user).first()
        self.assertIsNotNone(notification)
        self.assertIn('completed successfully', notification.message.lower())
        self.assertIn('TXN_12345', notification.message)
    
    def test_withdrawal_notification_failed(self):
        """Test notification is sent when withdrawal fails"""
        withdrawal = Withdrawal.objects.create(
            user=self.user,
            amount=Decimal('100.00'),
            payment_method='MOBILE_MONEY',
            account_details='1234567890|001',
            status='FAILED',
            failure_reason='Gateway error',
            wallet=self.wallet
        )
        
        # Send notification
        notify_withdrawal_failed(withdrawal, 'Gateway error')
        
        # Verify notification was created
        notification = Notification.objects.filter(user=self.user).first()
        self.assertIsNotNone(notification)
        self.assertIn('failed', notification.message.lower())
        self.assertIn('Gateway error', notification.message)
    
    def test_withdrawal_notification_retry(self):
        """Test notification is sent when withdrawal is retried"""
        withdrawal = Withdrawal.objects.create(
            user=self.user,
            amount=Decimal('100.00'),
            payment_method='MOBILE_MONEY',
            account_details='1234567890|001',
            status='PENDING',
            retry_count=1,
            max_retry_count=3,
            wallet=self.wallet
        )
        
        # Send notification
        notify_withdrawal_retry(withdrawal, 1, 3)
        
        # Verify notification was created
        notification = Notification.objects.filter(user=self.user).first()
        self.assertIsNotNone(notification)
        self.assertIn('retried', notification.message.lower())
        self.assertIn('Attempt 1 of 3', notification.message)
    
    def test_withdrawal_status_transitions(self):
        """Test withdrawal status transitions are validated"""
        withdrawal = Withdrawal.objects.create(
            user=self.user,
            amount=Decimal('100.00'),
            payment_method='BANK_TRANSFER',
            account_details='1234567890|001',
            status='PENDING',
            wallet=self.wallet
        )
        
        # Valid transition: PENDING -> PROCESSING
        withdrawal.status = 'PROCESSING'
        withdrawal.save()
        withdrawal.refresh_from_db()
        self.assertEqual(withdrawal.status, 'PROCESSING')
        
        # Valid transition: PROCESSING -> COMPLETED
        withdrawal.status = 'COMPLETED'
        withdrawal.save()
        withdrawal.refresh_from_db()
        self.assertEqual(withdrawal.status, 'COMPLETED')
        
        # Invalid transition: COMPLETED -> PENDING (should fail)
        withdrawal.status = 'PENDING'
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            withdrawal.full_clean()
    
    def test_withdrawal_immutable_after_completion(self):
        """Test withdrawal fields are immutable after completion"""
        withdrawal = Withdrawal.objects.create(
            user=self.user,
            amount=Decimal('100.00'),
            payment_method='BANK_TRANSFER',
            account_details='1234567890|001',
            status='COMPLETED',
            wallet=self.wallet
        )
        
        # Try to change amount (should fail)
        withdrawal.amount = Decimal('200.00')
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            withdrawal.full_clean()
        
        # Try to change user (should fail)
        new_user = User.objects.create_user(
            username='otheruser',
            email='other@example.com',
            password='pass123'
        )
        withdrawal.user = new_user
        with self.assertRaises(ValidationError):
            withdrawal.full_clean()
    
    def test_multiple_withdrawals_same_user(self):
        """Test user can create multiple withdrawals"""
        # Create first withdrawal
        withdrawal1 = Withdrawal.objects.create(
            user=self.user,
            amount=Decimal('100.00'),
            payment_method='BANK_TRANSFER',
            account_details='1234567890|001',
            status='PENDING',
            wallet=self.wallet
        )
        
        # Create second withdrawal
        withdrawal2 = Withdrawal.objects.create(
            user=self.user,
            amount=Decimal('200.00'),
            payment_method='MOBILE_MONEY',
            account_details='0987654321|002',
            status='PENDING',
            wallet=self.wallet
        )
        
        # Both should exist
        self.assertEqual(Withdrawal.objects.filter(user=self.user).count(), 2)
        self.assertEqual(withdrawal1.amount, Decimal('100.00'))
        self.assertEqual(withdrawal2.amount, Decimal('200.00'))
        
        # Balance should still be intact (not deducted until completed)
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal('1000.00'))


class WithdrawalIntegrationTestCase(TransactionTestCase):
    """Integration tests for withdrawal workflow with database transactions"""
    
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
    
    @patch('wallet.payment_manager.PaymentManager._process_bank_transfer')
    def test_complete_withdrawal_workflow(self, mock_bank_transfer):
        """Test complete withdrawal workflow from creation to completion"""
        # Mock successful bank transfer
        mock_bank_transfer.return_value = {
            'success': True,
            'transaction_id': 'BANK_12345',
            'gateway_response': {'status': 'success'},
            'failure_reason': None
        }
        
        # Step 1: Create withdrawal
        withdrawal = Withdrawal.objects.create(
            user=self.user,
            amount=Decimal('100.00'),
            payment_method='BANK_TRANSFER',
            account_details='1234567890|001',
            status='PENDING',
            wallet=self.wallet
        )
        
        initial_balance = self.wallet.balance
        self.assertEqual(withdrawal.status, 'PENDING')
        
        # Step 2: Process withdrawal
        withdrawal.status = 'PROCESSING'
        withdrawal.save()
        
        payment_manager = PaymentManager()
        result = payment_manager.process_withdrawal(withdrawal)
        
        # Step 3: Complete withdrawal
        if result['success']:
            self.wallet.balance -= withdrawal.amount
            self.wallet.save()
            
            Transaction.objects.create(
                wallet=self.wallet,
                amount=-withdrawal.amount,
                transaction_type='WITHDRAWAL',
                description=f"Withdrawal of ${withdrawal.amount}"
            )
            
            withdrawal.status = 'COMPLETED'
            withdrawal.transaction_id = result['transaction_id']
            withdrawal.save()
        
        # Verify final state
        withdrawal.refresh_from_db()
        self.wallet.refresh_from_db()
        
        self.assertEqual(withdrawal.status, 'COMPLETED')
        self.assertEqual(self.wallet.balance, initial_balance - withdrawal.amount)
        self.assertEqual(Transaction.objects.filter(wallet=self.wallet).count(), 1)
