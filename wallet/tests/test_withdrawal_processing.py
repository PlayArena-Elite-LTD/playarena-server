"""
Unit tests for withdrawal processing utility function

Tests verify that withdrawal processing, wallet debiting, and transaction creation work correctly.
"""

from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from decimal import Decimal

from wallet.models import Wallet, Transaction, Withdrawal
from wallet.utils import process_withdrawal_and_debit_wallet

User = get_user_model()


class WithdrawalProcessingTests(TestCase):
    """Test withdrawal processing and wallet debiting"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.wallet = Wallet.objects.create(user=self.user, balance=Decimal('1000.00'))
    
    def test_process_withdrawal_success(self):
        """Test successful withdrawal processing"""
        # Create withdrawal
        withdrawal = Withdrawal.objects.create(
            user=self.user,
            amount=Decimal('100.00'),
            payment_method='PAYSTACK',
            account_details='Account Number: 1234567890',
            status='PENDING',
            wallet=self.wallet
        )
        
        initial_balance = self.wallet.balance
        initial_transaction_count = Transaction.objects.count()
        
        # Process withdrawal
        result = process_withdrawal_and_debit_wallet(withdrawal)
        
        self.assertTrue(result['success'])
        self.assertTrue(result['wallet_debited'])
        self.assertTrue(result['transaction_created'])
        
        # Verify withdrawal status
        withdrawal.refresh_from_db()
        self.assertEqual(withdrawal.status, 'COMPLETED')
        
        # Verify wallet balance
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, initial_balance - Decimal('100.00'))
        self.assertEqual(result['new_balance'], self.wallet.balance)
        
        # Verify transaction created
        self.assertEqual(Transaction.objects.count(), initial_transaction_count + 1)
        transaction = Transaction.objects.latest('created_at')
        self.assertEqual(transaction.amount, -Decimal('100.00'))  # Negative for withdrawal
        self.assertEqual(transaction.transaction_type, 'WITHDRAWAL')
        self.assertEqual(transaction.wallet, self.wallet)
        self.assertIn('Withdrawal of $100.00', transaction.description)
    
    def test_idempotent_withdrawal_processing(self):
        """Test that withdrawal processing is idempotent (won't debit twice)"""
        # Create and process withdrawal
        withdrawal = Withdrawal.objects.create(
            user=self.user,
            amount=Decimal('50.00'),
            payment_method='FLUTTERWAVE',
            account_details='Account Number: 9876543210',
            status='PENDING',
            wallet=self.wallet
        )
        
        initial_balance = self.wallet.balance
        
        # First processing
        result1 = process_withdrawal_and_debit_wallet(withdrawal)
        self.assertTrue(result1['success'])
        self.assertTrue(result1['wallet_debited'])
        
        self.wallet.refresh_from_db()
        balance_after_first = self.wallet.balance
        self.assertEqual(balance_after_first, initial_balance - Decimal('50.00'))
        
        # Second processing attempt (should be idempotent)
        withdrawal.refresh_from_db()
        result2 = process_withdrawal_and_debit_wallet(withdrawal)
        self.assertTrue(result2['success'])
        # Should detect already debited
        self.assertFalse(result2['wallet_debited'])  # Or already debited
        
        self.wallet.refresh_from_db()
        balance_after_second = self.wallet.balance
        # Balance should not decrease again
        self.assertEqual(balance_after_second, balance_after_first)
    
    def test_process_failed_withdrawal(self):
        """Test that failed withdrawals cannot be processed"""
        withdrawal = Withdrawal.objects.create(
            user=self.user,
            amount=Decimal('100.00'),
            payment_method='PAYSTACK',
            account_details='Account Number: 1234567890',
            status='FAILED',
            wallet=self.wallet
        )
        
        initial_balance = self.wallet.balance
        initial_transaction_count = Transaction.objects.count()
        
        # Try to process failed withdrawal
        result = process_withdrawal_and_debit_wallet(withdrawal)
        
        self.assertFalse(result['success'])
        self.assertFalse(result['wallet_debited'])
        self.assertFalse(result['transaction_created'])
        
        # Balance should not change
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, initial_balance)
        
        # No transaction should be created
        self.assertEqual(Transaction.objects.count(), initial_transaction_count)
    
    def test_process_cancelled_withdrawal(self):
        """Test that cancelled withdrawals cannot be processed"""
        withdrawal = Withdrawal.objects.create(
            user=self.user,
            amount=Decimal('100.00'),
            payment_method='PAYSTACK',
            account_details='Account Number: 1234567890',
            status='CANCELLED',
            wallet=self.wallet
        )
        
        initial_balance = self.wallet.balance
        
        # Try to process cancelled withdrawal
        result = process_withdrawal_and_debit_wallet(withdrawal)
        
        self.assertFalse(result['success'])
        self.assertFalse(result['wallet_debited'])
        
        # Balance should not change
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, initial_balance)
    
    def test_insufficient_balance_protection(self):
        """Test that insufficient balance prevents withdrawal processing"""
        # Create withdrawal for more than available balance
        withdrawal = Withdrawal.objects.create(
            user=self.user,
            amount=Decimal('1500.00'),  # More than $1000 balance
            payment_method='PAYSTACK',
            account_details='Account Number: 1234567890',
            status='PENDING',
            wallet=self.wallet
        )
        
        initial_balance = self.wallet.balance
        initial_transaction_count = Transaction.objects.count()
        
        # Try to process withdrawal
        result = process_withdrawal_and_debit_wallet(withdrawal)
        
        self.assertFalse(result['success'])
        self.assertFalse(result['wallet_debited'])
        self.assertFalse(result['transaction_created'])
        self.assertIn('Insufficient balance', result['message'])
        
        # Balance should not change
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, initial_balance)
        
        # No transaction should be created
        self.assertEqual(Transaction.objects.count(), initial_transaction_count)
    
    def test_atomic_transaction_rollback(self):
        """Test that failed transactions roll back completely"""
        withdrawal = Withdrawal.objects.create(
            user=self.user,
            amount=Decimal('100.00'),
            payment_method='PAYSTACK',
            account_details='Account Number: 1234567890',
            status='PENDING',
            wallet=self.wallet
        )
        
        initial_balance = self.wallet.balance
        initial_transaction_count = Transaction.objects.count()
        
        # Simulate error by making withdrawal invalid (delete wallet reference)
        withdrawal.wallet = None
        withdrawal.save()
        
        # Try to process (will fail due to missing wallet)
        result = process_withdrawal_and_debit_wallet(withdrawal)
        
        # Should handle error gracefully
        # Balance should not change (transaction rolled back)
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, initial_balance)
        
        # No transaction should be created
        self.assertEqual(Transaction.objects.count(), initial_transaction_count)
    
    def test_process_processing_status_withdrawal(self):
        """Test that PROCESSING status withdrawals can be completed"""
        withdrawal = Withdrawal.objects.create(
            user=self.user,
            amount=Decimal('75.00'),
            payment_method='FLUTTERWAVE',
            account_details='Account Number: 1111111111',
            status='PROCESSING',
            wallet=self.wallet
        )
        
        initial_balance = self.wallet.balance
        
        # Process withdrawal
        result = process_withdrawal_and_debit_wallet(withdrawal)
        
        self.assertTrue(result['success'])
        self.assertTrue(result['wallet_debited'])
        
        # Verify status updated
        withdrawal.refresh_from_db()
        self.assertEqual(withdrawal.status, 'COMPLETED')
        
        # Verify balance debited
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, initial_balance - Decimal('75.00'))
    
    def test_multiple_withdrawals_sequential(self):
        """Test processing multiple withdrawals sequentially"""
        # First withdrawal
        withdrawal1 = Withdrawal.objects.create(
            user=self.user,
            amount=Decimal('100.00'),
            payment_method='PAYSTACK',
            account_details='Account 1',
            status='PENDING',
            wallet=self.wallet
        )
        
        result1 = process_withdrawal_and_debit_wallet(withdrawal1)
        self.assertTrue(result1['success'])
        
        self.wallet.refresh_from_db()
        balance_after_first = self.wallet.balance
        self.assertEqual(balance_after_first, Decimal('900.00'))
        
        # Second withdrawal
        withdrawal2 = Withdrawal.objects.create(
            user=self.user,
            amount=Decimal('200.00'),
            payment_method='FLUTTERWAVE',
            account_details='Account 2',
            status='PENDING',
            wallet=self.wallet
        )
        
        result2 = process_withdrawal_and_debit_wallet(withdrawal2)
        self.assertTrue(result2['success'])
        
        self.wallet.refresh_from_db()
        balance_after_second = self.wallet.balance
        self.assertEqual(balance_after_second, Decimal('700.00'))
        
        # Verify both transactions created
        transactions = Transaction.objects.filter(
            transaction_type='WITHDRAWAL',
            wallet=self.wallet
        ).order_by('created_at')
        
        self.assertEqual(transactions.count(), 2)
        self.assertEqual(transactions[0].amount, -Decimal('100.00'))
        self.assertEqual(transactions[1].amount, -Decimal('200.00'))
    
    def test_withdrawal_not_found(self):
        """Test handling of non-existent withdrawal"""
        # Create a withdrawal object but don't save it
        withdrawal = Withdrawal(
            id=99999,  # Non-existent ID
            user=self.user,
            amount=Decimal('100.00'),
            payment_method='PAYSTACK',
            account_details='Account Number: 1234567890',
            wallet=self.wallet
        )
        
        result = process_withdrawal_and_debit_wallet(withdrawal)
        
        self.assertFalse(result['success'])
        self.assertFalse(result['wallet_debited'])
        self.assertIn('not found', result['message'])
    
    def test_transaction_description_format(self):
        """Test that transaction description is properly formatted"""
        withdrawal = Withdrawal.objects.create(
            user=self.user,
            amount=Decimal('250.50'),
            payment_method='PAYSTACK',
            account_details='Account Number: 1234567890',
            status='PENDING',
            wallet=self.wallet
        )
        
        result = process_withdrawal_and_debit_wallet(withdrawal)
        self.assertTrue(result['success'])
        
        transaction = Transaction.objects.latest('created_at')
        self.assertIn('Withdrawal of $250.50', transaction.description)
        self.assertIn('Paystack', transaction.description)
