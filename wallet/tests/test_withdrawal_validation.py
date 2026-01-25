"""
Unit tests for withdrawal validation and security features

Tests verify that withdrawal limits, daily limits, and security checks are properly implemented.
"""

from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from decimal import Decimal
from datetime import timedelta

from wallet.models import Wallet, Withdrawal
from wallet.error_handlers import (
    validate_withdrawal_amount,
    PaymentValidationError
)
from django.db.models import Sum

User = get_user_model()


class WithdrawalValidationTests(TestCase):
    """Test withdrawal validation and security features"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.wallet = Wallet.objects.create(user=self.user, balance=Decimal('1000.00'))
    
    def test_minimum_withdrawal_amount(self):
        """Test that minimum withdrawal amount is enforced"""
        # Valid amount (at minimum)
        amount = validate_withdrawal_amount(Decimal('1.00'), self.user)
        self.assertEqual(amount, Decimal('1.00'))
        
        # Amount below minimum
        with self.assertRaises(PaymentValidationError) as context:
            validate_withdrawal_amount(Decimal('0.50'), self.user)
        self.assertIn('Minimum withdrawal amount', str(context.exception.user_message))
    
    def test_maximum_withdrawal_amount(self):
        """Test that maximum single withdrawal amount is enforced"""
        # Valid amount (at maximum)
        amount = validate_withdrawal_amount(Decimal('5000.00'), self.user)
        self.assertEqual(amount, Decimal('5000.00'))
        
        # Amount above maximum
        with self.assertRaises(PaymentValidationError) as context:
            validate_withdrawal_amount(Decimal('6000.00'), self.user)
        self.assertIn('Maximum withdrawal amount', str(context.exception.user_message))
    
    def test_insufficient_balance(self):
        """Test that insufficient balance is detected"""
        # User has $1000, try to withdraw $1500
        with self.assertRaises(PaymentValidationError) as context:
            validate_withdrawal_amount(Decimal('1500.00'), self.user)
        self.assertIn('Insufficient balance', str(context.exception.user_message))
    
    def test_negative_amount(self):
        """Test that negative amounts are rejected"""
        with self.assertRaises(PaymentValidationError) as context:
            validate_withdrawal_amount(Decimal('-10.00'), self.user)
        self.assertIn('must be greater than zero', str(context.exception.user_message))
    
    def test_zero_amount(self):
        """Test that zero amounts are rejected"""
        with self.assertRaises(PaymentValidationError) as context:
            validate_withdrawal_amount(Decimal('0.00'), self.user)
        self.assertIn('must be greater than zero', str(context.exception.user_message))
    
    def test_daily_withdrawal_count_limit(self):
        """Test that daily withdrawal count limit is enforced"""
        # Create maximum allowed withdrawals for today
        for i in range(Withdrawal.MAX_DAILY_WITHDRAWAL_COUNT):
            Withdrawal.objects.create(
                user=self.user,
                amount=Decimal('10.00'),
                payment_method='PAYSTACK',
                account_details=f'Account {i}',
                status='COMPLETED',
                wallet=self.wallet
            )
        
        # Try to create one more (should fail)
        with self.assertRaises(PaymentValidationError) as context:
            validate_withdrawal_amount(Decimal('10.00'), self.user)
        self.assertIn('Daily withdrawal limit reached', str(context.exception.user_message))
        self.assertIn(f'Maximum {Withdrawal.MAX_DAILY_WITHDRAWAL_COUNT}', str(context.exception.user_message))
    
    def test_daily_withdrawal_amount_limit(self):
        """Test that daily withdrawal amount limit is enforced"""
        # Create withdrawals totaling near the limit
        total_withdrawn = Decimal('9500.00')
        Withdrawal.objects.create(
            user=self.user,
            amount=total_withdrawn,
            payment_method='PAYSTACK',
            account_details='Account 1',
            status='COMPLETED',
            wallet=self.wallet
        )
        
        # Try to withdraw amount that would exceed daily limit
        with self.assertRaises(PaymentValidationError) as context:
            validate_withdrawal_amount(Decimal('600.00'), self.user)  # Would make total $10,100
        self.assertIn('Daily withdrawal amount limit exceeded', str(context.exception.user_message))
        self.assertIn(f'Maximum ${Withdrawal.MAX_DAILY_WITHDRAWAL_AMOUNT:.2f}', str(context.exception.user_message))
    
    def test_daily_limit_with_remaining_amount(self):
        """Test that remaining daily limit is calculated correctly"""
        # Create withdrawal of $8000
        Withdrawal.objects.create(
            user=self.user,
            amount=Decimal('8000.00'),
            payment_method='PAYSTACK',
            account_details='Account 1',
            status='COMPLETED',
            wallet=self.wallet
        )
        
        # Try to withdraw amount that would exceed limit
        with self.assertRaises(PaymentValidationError) as context:
            validate_withdrawal_amount(Decimal('2500.00'), self.user)  # Would make total $10,500
        
        # Should show remaining amount
        error_msg = str(context.exception.user_message)
        self.assertIn('Daily withdrawal amount limit exceeded', error_msg)
        # Should mention remaining amount ($2000)
        self.assertIn('$2000.00', error_msg)  # $10,000 - $8,000 = $2,000
    
    def test_daily_limit_only_counts_today(self):
        """Test that daily limits only count today's withdrawals"""
        # Create withdrawal from yesterday
        yesterday = timezone.now() - timedelta(days=1)
        Withdrawal.objects.create(
            user=self.user,
            amount=Decimal('5000.00'),
            payment_method='PAYSTACK',
            account_details='Account 1',
            status='COMPLETED',
            wallet=self.wallet,
            created_at=yesterday
        )
        
        # Should still be able to withdraw today's limit
        amount = validate_withdrawal_amount(Decimal('10000.00'), self.user)
        self.assertEqual(amount, Decimal('10000.00'))
    
    def test_daily_limit_only_counts_relevant_statuses(self):
        """Test that only PENDING, PROCESSING, and COMPLETED withdrawals count toward limits"""
        # Create cancelled withdrawal (should not count)
        Withdrawal.objects.create(
            user=self.user,
            amount=Decimal('5000.00'),
            payment_method='PAYSTACK',
            account_details='Account 1',
            status='CANCELLED',
            wallet=self.wallet
        )
        
        # Create failed withdrawal (should not count)
        Withdrawal.objects.create(
            user=self.user,
            amount=Decimal('5000.00'),
            payment_method='PAYSTACK',
            account_details='Account 2',
            status='FAILED',
            wallet=self.wallet
        )
        
        # Should still be able to withdraw full daily limit
        amount = validate_withdrawal_amount(Decimal('10000.00'), self.user)
        self.assertEqual(amount, Decimal('10000.00'))
    
    def test_model_clean_validation(self):
        """Test that model clean() method enforces validation"""
        # Test minimum amount
        withdrawal = Withdrawal(
            user=self.user,
            amount=Decimal('0.50'),
            payment_method='PAYSTACK',
            account_details='Account 1',
            wallet=self.wallet
        )
        with self.assertRaises(Exception):  # ValidationError
            withdrawal.full_clean()
        
        # Test maximum amount
        withdrawal = Withdrawal(
            user=self.user,
            amount=Decimal('6000.00'),
            payment_method='PAYSTACK',
            account_details='Account 1',
            wallet=self.wallet
        )
        with self.assertRaises(Exception):  # ValidationError
            withdrawal.full_clean()
        
        # Test missing account details
        withdrawal = Withdrawal(
            user=self.user,
            amount=Decimal('100.00'),
            payment_method='PAYSTACK',
            account_details='',
            wallet=self.wallet
        )
        with self.assertRaises(Exception):  # ValidationError
            withdrawal.full_clean()
    
    def test_valid_withdrawal_passes_all_checks(self):
        """Test that a valid withdrawal passes all validation checks"""
        amount = validate_withdrawal_amount(Decimal('100.00'), self.user)
        self.assertEqual(amount, Decimal('100.00'))
        
        # Should be able to create withdrawal
        withdrawal = Withdrawal(
            user=self.user,
            amount=amount,
            payment_method='PAYSTACK',
            account_details='Account Number: 1234567890',
            wallet=self.wallet
        )
        withdrawal.full_clean()  # Should not raise
        withdrawal.save()  # Should save successfully
    
    def test_multiple_withdrawals_same_day(self):
        """Test multiple withdrawals on the same day within limits"""
        # First withdrawal
        amount1 = validate_withdrawal_amount(Decimal('2000.00'), self.user)
        self.assertEqual(amount1, Decimal('2000.00'))
        
        withdrawal1 = Withdrawal.objects.create(
            user=self.user,
            amount=amount1,
            payment_method='PAYSTACK',
            account_details='Account 1',
            status='COMPLETED',
            wallet=self.wallet
        )
        
        # Second withdrawal (should still be valid)
        amount2 = validate_withdrawal_amount(Decimal('3000.00'), self.user)
        self.assertEqual(amount2, Decimal('3000.00'))
        
        withdrawal2 = Withdrawal.objects.create(
            user=self.user,
            amount=amount2,
            payment_method='PAYSTACK',
            account_details='Account 2',
            status='COMPLETED',
            wallet=self.wallet
        )
        
        # Third withdrawal (should still be valid, total = $5000)
        amount3 = validate_withdrawal_amount(Decimal('5000.00'), self.user)
        self.assertEqual(amount3, Decimal('5000.00'))
        
        # Total should be $10,000 (at limit)
        total = Withdrawal.objects.filter(
            user=self.user,
            created_at__gte=timezone.now().replace(hour=0, minute=0, second=0, microsecond=0),
            status__in=['PENDING', 'PROCESSING', 'COMPLETED']
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        
        self.assertEqual(total, Decimal('10000.00'))
        
        # Next withdrawal should fail
        with self.assertRaises(PaymentValidationError):
            validate_withdrawal_amount(Decimal('1.00'), self.user)
    
    def test_daily_limit_resets_at_midnight(self):
        """Test that daily limits reset at midnight"""
        # Create withdrawal at 11:59 PM yesterday
        yesterday_late = timezone.now().replace(hour=23, minute=59, second=0, microsecond=0) - timedelta(days=1)
        Withdrawal.objects.create(
            user=self.user,
            amount=Decimal('10000.00'),
            payment_method='PAYSTACK',
            account_details='Account 1',
            status='COMPLETED',
            wallet=self.wallet,
            created_at=yesterday_late
        )
        
        # Should be able to withdraw today's limit
        amount = validate_withdrawal_amount(Decimal('10000.00'), self.user)
        self.assertEqual(amount, Decimal('10000.00'))
