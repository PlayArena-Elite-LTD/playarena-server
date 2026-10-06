from django.db import models
from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver
from decimal import Decimal
import logging


class Wallet(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='wallet')
    balance = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    
    def verify_balance_integrity(self):
        """
        Security: Verify that wallet balance matches the sum of all transactions.
        
        Returns:
            dict: {
                'is_valid': bool,
                'expected_balance': Decimal,
                'actual_balance': Decimal,
                'discrepancy': Decimal,
                'transaction_count': int
            }
        """
        from django.db.models import Sum
        from decimal import Decimal
        
        # Calculate expected balance from transactions
        transaction_sum = self.transactions.aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0.00')
        
        expected_balance = transaction_sum
        actual_balance = self.balance
        discrepancy = actual_balance - expected_balance
        transaction_count = self.transactions.count()
        
        return {
            'is_valid': discrepancy == Decimal('0.00'),
            'expected_balance': expected_balance,
            'actual_balance': actual_balance,
            'discrepancy': discrepancy,
            'transaction_count': transaction_count,
        }
    
    def recalculate_balance(self):
        """
        Security: Recalculate balance from transactions and update wallet.
        Use this to fix discrepancies detected by verify_balance_integrity().
        
        Returns:
            Decimal: The recalculated balance
        """
        from django.db.models import Sum
        from decimal import Decimal
        
        # Calculate balance from transactions
        transaction_sum = self.transactions.aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0.00')
        
        # Update balance
        self.balance = transaction_sum
        self.save(update_fields=['balance'])
        
        return self.balance
    
    @classmethod
    def find_wallets_with_discrepancies(cls):
        """
        Security: Find all wallets where balance doesn't match transaction sum.
        
        Returns:
            QuerySet: Wallets with discrepancies
        """
        from django.db.models import Sum, F, DecimalField
        from django.db.models.functions import Coalesce
        
        # Get all wallets and calculate expected balances
        wallets_with_discrepancies = cls.objects.annotate(
            expected_balance=Coalesce(
                Sum('transactions__amount'),
                0,
                output_field=DecimalField(max_digits=10, decimal_places=2)
            )
        ).exclude(
            balance=F('expected_balance')
        )
        
        return wallets_with_discrepancies
    
    @classmethod
    def reconcile_all_wallets(cls, dry_run=False):
        """
        Security: Reconcile all wallets by recalculating balances from transactions.
        
        Args:
            dry_run (bool): If True, only report discrepancies without fixing them.
        
        Returns:
            dict: {
                'total_wallets': int,
                'wallets_with_discrepancies': int,
                'wallets_fixed': int,
                'discrepancies': list of dicts
            }
        """
        from decimal import Decimal
        
        all_wallets = cls.objects.all()
        total_count = all_wallets.count()
        discrepancies_found = []
        wallets_fixed = 0
        
        for wallet in all_wallets:
            result = wallet.verify_balance_integrity()
            if not result['is_valid']:
                discrepancies_found.append({
                    'wallet_id': wallet.id,
                    'user': wallet.user.username if wallet.user else 'None',
                    'expected': result['expected_balance'],
                    'actual': result['actual_balance'],
                    'discrepancy': result['discrepancy'],
                    'transaction_count': result['transaction_count'],
                })
                
                if not dry_run:
                    wallet.recalculate_balance()
                    wallets_fixed += 1
        
        return {
            'total_wallets': total_count,
            'wallets_with_discrepancies': len(discrepancies_found),
            'wallets_fixed': wallets_fixed if not dry_run else 0,
            'discrepancies': discrepancies_found,
            'dry_run': dry_run,
        }


class PaymentGatewaySetting(models.Model):
    """Singleton runtime switch for deposit gateway selection."""

    PROVIDER_CHOICES = [
        ('lipila', 'Lipila'),
        ('zynle', 'ZynlePay'),
    ]

    active_provider = models.CharField(
        max_length=20,
        choices=PROVIDER_CHOICES,
        default='lipila',
        help_text='New deposits use this gateway. Existing deposits keep their original gateway.',
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Payment gateway setting'
        verbose_name_plural = 'Payment gateway settings'

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        return None

    def __str__(self):
        return f'Active deposit gateway: {self.get_active_provider_display()}'


class Transaction(models.Model):
    TRANSACTION_TYPES = [
        ('DEPOSIT', 'Deposit'),
        ('WITHDRAWAL', 'Withdrawal'),
        ('MATCH_CREATION', 'Match Creation'),
        ('MATCH_JOINING', 'Match Joining'),
        ('MATCH_WINNINGS', 'Match Winnings'),
        ('MATCH_REFUND', 'Match Refund'),
        ('MATCH_DRAW_RETURN', 'Match Draw Return'),
        ('TOURNAMENT_JOINING', 'Tournament Joining'),
        ('TOURNAMENT_REFUND', 'Tournament Refund'),
        ('TOURNAMENT_WINNINGS', 'Tournament Winnings'),
        ('REFERRAL_TRANSFER', 'Referral Commission Transfer'),
        ('REFERRAL_REVERSAL', 'Referral Commission Reversal'),
        ('OTHER', 'Other'),
    ]

    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name='transactions')
    amount = models.DecimalField(max_digits=10, decimal_places=2)  # Positive for credits, negative for debits
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)
    description = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    related_match = models.ForeignKey('matches.Match', on_delete=models.SET_NULL, null=True, blank=True)
    related_tournament = models.ForeignKey('matches.Tournament', on_delete=models.SET_NULL, null=True, blank=True)
    
    @property
    def is_credit(self):
        return self.amount > 0
        
    def __str__(self):
        return f"{'+' if self.is_credit else '-'}{abs(self.amount)} - {self.get_transaction_type_display()} - {self.created_at.strftime('%Y-%m-%d %H:%M')}"

class Deposit(models.Model):
    """Model to track user deposits with payment gateway integration
    
    Security features:
    - Amount validation (positive, within limits)
    - Status transition validation
    - Automatic wallet linking
    - Immutable fields after completion
    """
    
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PROCESSING', 'Processing'),
        ('COMPLETED', 'Completed'),
        ('FAILED', 'Failed'),
        ('CANCELLED', 'Cancelled'),
    ]
    
    PROVIDER_PAYMENT_STATUS_CHOICES = [
        ('Pending', 'Pending'),
        ('Successful', 'Successful'),
        ('Failed', 'Failed'),
    ]

    PAYMENT_METHOD_CHOICES = [
        ('LIPILA', 'Lipila (Card)'),
        ('LIPILA_MOMO', 'Lipila (Mobile Money)'),
        ('ZYNLE_MOMO', 'ZynlePay (Mobile Money)'),
        # Legacy values (kept to avoid breaking existing rows / admin edits)
        ('PESAPAL', 'Pesapal (legacy)'),
        ('ZYNELPAY', 'Zynel Pay (legacy)'),
        ('PAYPAL', 'PayPal (legacy)'),
        ('STRIPE', 'Stripe (legacy)'),
        ('MOBILE_MONEY', 'Mobile Money (legacy)'),
        ('BANK_TRANSFER', 'Bank Transfer'),
        ('OTHER', 'Other'),
    ]
    
    # Security: Maximum deposit amount to prevent abuse
    MAX_DEPOSIT_AMOUNT = Decimal('10000.00')
    MIN_DEPOSIT_AMOUNT = Decimal('1.00')
    
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='deposits')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES)
    transaction_id = models.CharField(max_length=255, blank=True, null=True, help_text='Payment gateway transaction ID')
    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name='deposits', null=True, blank=True)
    
    # Security fields added by migration 0004_add_payment_security_fields
    gateway_response = models.JSONField(default=dict, blank=True, help_text='Full gateway response stored as JSON (for audit and debugging)')
    gateway_transaction_id = models.CharField(max_length=255, blank=True, null=True, help_text='Additional gateway transaction identifier (e.g., flw_ref for Flutterwave)')
    payment_provider = models.CharField(
        max_length=32,
        blank=True,
        null=True,
        db_index=True,
        help_text='Gateway slug used for this deposit (e.g. lipila or zynle)',
    )
    provider_transaction_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        db_index=True,
        help_text='Provider transaction identifier',
    )
    provider_payment_status = models.CharField(
        max_length=20,
        choices=PROVIDER_PAYMENT_STATUS_CHOICES,
        blank=True,
        null=True,
        db_index=True,
        help_text='Authoritative provider status (Pending, Successful, Failed)',
    )
    idempotency_key = models.CharField(
        max_length=64,
        blank=True,
        null=True,
        unique=True,
        help_text='Idempotency key for payment initiation',
    )
    raw_webhook_payload = models.JSONField(
        default=dict,
        blank=True,
        help_text='Last webhook payload from provider (debugging)',
    )
    payment_reference = models.CharField(max_length=255, blank=True, null=True, unique=True, db_index=True, help_text='Unique payment reference (prevents duplicate payments)')
    ip_address = models.GenericIPAddressField(blank=True, null=True, help_text='IP address of the user when deposit was initiated (for fraud detection)')
    user_agent = models.CharField(max_length=500, blank=True, null=True, help_text='User agent string (for security tracking)')
    completed_at = models.DateTimeField(blank=True, null=True, help_text='Timestamp when payment was completed')
    failure_reason = models.TextField(blank=True, null=True, help_text='Reason for payment failure (if applicable)')
    retry_count = models.PositiveIntegerField(default=0, help_text='Number of retry attempts (prevents infinite retries)')
    verification_hash = models.CharField(max_length=64, blank=True, null=True, help_text='SHA256 hash of payment data to prevent tampering')
    webhook_signature = models.CharField(max_length=255, blank=True, null=True, help_text='Webhook signature for verification')
    webhook_verified = models.BooleanField(default=False, help_text='Whether webhook signature was verified')
    last_webhook_at = models.DateTimeField(blank=True, null=True, help_text='Timestamp of last webhook received')
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Deposit'
        verbose_name_plural = 'Deposits'
        # Security: Add index for faster queries and prevent duplicate transaction IDs
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['status']),
            models.Index(fields=['payment_provider', 'provider_payment_status']),
            models.Index(fields=['provider_transaction_id']),
        ]
        constraints = [
            # Security: Ensure transaction_id is unique (prevent duplicate processing)
            models.UniqueConstraint(
                fields=['transaction_id'],
                condition=models.Q(transaction_id__isnull=False),
                name='unique_deposit_transaction_id'
            ),
        ]
    
    def __str__(self):
        return f"Deposit ZMW {self.amount} - {self.get_status_display()} - {self.user.username}"
    
    def clean(self):
        """Security: Validate deposit amount and business rules"""
        from django.core.exceptions import ValidationError
        
        # Validate amount is positive
        if self.amount <= 0:
            raise ValidationError({'amount': 'Deposit amount must be positive'})
        
        # Validate minimum deposit amount
        if self.amount < self.MIN_DEPOSIT_AMOUNT:
            raise ValidationError({'amount': f'Minimum deposit amount is ZMW {self.MIN_DEPOSIT_AMOUNT}'})
        
        # Validate maximum deposit amount
        if self.amount > self.MAX_DEPOSIT_AMOUNT:
            raise ValidationError({'amount': f'Maximum deposit amount is ZMW {self.MAX_DEPOSIT_AMOUNT}'})
        
        # Security: Validate status transitions (prevent invalid state changes)
        if self.pk:  # Only validate transitions for existing deposits
            old_instance = Deposit.objects.get(pk=self.pk)
            old_status = old_instance.status
            
            # Cannot change from COMPLETED, FAILED, or CANCELLED
            if old_status in ['COMPLETED', 'FAILED', 'CANCELLED']:
                if self.status != old_status:
                    raise ValidationError(
                        {'status': f'Cannot change status from {old_status} to {self.status}'}
                    )
            
            # Security: Cannot change amount after creation
            if self.amount != old_instance.amount:
                raise ValidationError({'amount': 'Cannot modify deposit amount after creation'})
            
            # Security: Cannot change user after creation
            if self.user_id != old_instance.user_id:
                raise ValidationError({'user': 'Cannot change deposit user after creation'})
    
    def generate_verification_hash(self):
        """
        Generate SHA256 hash of payment data to prevent tampering.
        
        Security: Creates a hash from critical deposit fields to ensure integrity.
        """
        import hashlib
        
        # Create hash from critical fields (handle case where id might be None for new deposits)
        deposit_id = self.id if self.id else 0
        transaction_id = self.transaction_id or ''
        hash_data = f"{deposit_id}_{self.user_id}_{self.amount}_{self.status}_{transaction_id}_{self.payment_method}"
        return hashlib.sha256(hash_data.encode()).hexdigest()
    
    def verify_hash(self):
        """
        Verify that the current deposit data matches the stored verification hash.
        
        Security: Detects if deposit data has been tampered with.
        
        Returns:
            bool: True if hash matches, False otherwise
        """
        if not self.verification_hash:
            return False
        
        current_hash = self.generate_verification_hash()
        return current_hash == self.verification_hash
    
    def save(self, *args, **kwargs):
        """Security: Run validation and auto-link wallet"""
        # Run full validation
        self.full_clean()
        
        # Automatically link to user's wallet if not set
        if not self.wallet:
            self.wallet = self.user.wallet
        
        super().save(*args, **kwargs)
    
    @property
    def can_be_cancelled(self):
        """Security: Check if deposit can be cancelled"""
        return self.status in ['PENDING', 'PROCESSING']
    
    @property
    def is_completed(self):
        """Check if deposit is completed"""
        return self.status == 'COMPLETED'
    
    @property
    def is_final(self):
        """Security: Check if deposit is in a final state (cannot be changed)"""
        return self.status in ['COMPLETED', 'FAILED', 'CANCELLED']

class Withdrawal(models.Model):
    """Model to track user withdrawals with payment gateway integration
    
    Security features:
    - Amount validation (positive, within limits, balance checks)
    - Status transition validation
    - Account details validation
    - Immutable fields after completion
    """
    
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PROCESSING', 'Processing'),
        ('COMPLETED', 'Completed'),
        ('FAILED', 'Failed'),
        ('CANCELLED', 'Cancelled'),
    ]
    
    PAYMENT_METHOD_CHOICES = [
        ('BANK_TRANSFER', 'Bank Transfer'),
        ('MOBILE_MONEY', 'Mobile Money'),
        # Legacy values (kept to avoid breaking existing rows / admin edits)
        ('ZYNELPAY', 'Zynel Pay (legacy)'),
        ('PAYPAL', 'PayPal (legacy)'),
        ('STRIPE', 'Stripe (legacy)'),
        ('OTHER', 'Other'),
    ]
    
    # Security: Withdrawal amount limits
    MIN_WITHDRAWAL_AMOUNT = Decimal('1.00')  # Match deposit minimum for consistency
    MAX_WITHDRAWAL_AMOUNT = Decimal('50000.00')  # Maximum per transaction
    DAILY_WITHDRAWAL_LIMIT = Decimal('100000.00')  # Maximum per day per user
    
    # Per-payment-method limits
    PAYMENT_METHOD_LIMITS = {
        'BANK_TRANSFER': {'max': Decimal('50000.00'), 'daily': Decimal('100000.00')},
        'MOBILE_MONEY': {'max': Decimal('10000.00'), 'daily': Decimal('50000.00')},
        'OTHER': {'max': Decimal('10000.00'), 'daily': Decimal('25000.00')},
    }
    
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='withdrawals')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES)
    account_details = models.TextField(help_text='Account information for withdrawal (account number, mobile number, etc.)')
    transaction_id = models.CharField(max_length=255, blank=True, null=True, help_text='Payment gateway transaction ID')
    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name='withdrawals', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Enhanced fields for retry and tracking (Task 15)
    gateway_response = models.JSONField(default=dict, blank=True, help_text='Full response from payment gateway')
    failure_reason = models.TextField(blank=True, null=True, help_text='Reason for withdrawal failure')
    retry_count = models.PositiveIntegerField(default=0, help_text='Number of retry attempts')
    max_retry_count = models.PositiveIntegerField(default=3, help_text='Maximum retry attempts allowed')
    gateway_transaction_id = models.CharField(max_length=255, blank=True, null=True, help_text='Payment gateway transaction ID (alternative to transaction_id)')
    ip_address = models.GenericIPAddressField(blank=True, null=True, help_text='IP address of withdrawal request')
    user_agent = models.CharField(max_length=500, blank=True, null=True, help_text='User agent of withdrawal request')
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Withdrawal'
        verbose_name_plural = 'Withdrawals'
        # Security: Add index for faster queries
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['status']),
            models.Index(fields=['retry_count']),  # For efficient retry queries
        ]
        constraints = [
            # Security: Ensure transaction_id is unique (prevent duplicate processing)
            models.UniqueConstraint(
                fields=['transaction_id'],
                condition=models.Q(transaction_id__isnull=False),
                name='unique_withdrawal_transaction_id'
            ),
        ]
    
    def __str__(self):
        return f"Withdrawal ZMW {self.amount} - {self.get_status_display()} - {self.user.username}"
    
    def clean(self):
        """Security: Validate withdrawal amount and business rules"""
        from django.core.exceptions import ValidationError
        
        # Validate amount is positive
        if self.amount <= 0:
            raise ValidationError({'amount': 'Withdrawal amount must be positive'})
        
        # Validate minimum withdrawal amount
        if self.amount < self.MIN_WITHDRAWAL_AMOUNT:
            raise ValidationError({'amount': f'Minimum withdrawal amount is ZMW {self.MIN_WITHDRAWAL_AMOUNT}'})
        
        # Validate maximum withdrawal amount (global limit)
        if self.amount > self.MAX_WITHDRAWAL_AMOUNT:
            raise ValidationError({'amount': f'Maximum withdrawal amount per transaction is ZMW {self.MAX_WITHDRAWAL_AMOUNT}'})
        
        # Validate per-payment-method limits
        if self.payment_method in self.PAYMENT_METHOD_LIMITS:
            method_limits = self.PAYMENT_METHOD_LIMITS[self.payment_method]
            if self.amount > method_limits['max']:
                raise ValidationError({
                    'amount': f'Maximum withdrawal amount for {self.get_payment_method_display()} is ZMW {method_limits["max"]}'
                })
        
        # Security: Validate account details are provided
        if not self.account_details or not self.account_details.strip():
            raise ValidationError({'account_details': 'Account details are required for withdrawal'})
        
        # Security: Validate balance when creating the withdrawal. The actual
        # wallet debit is applied only after the withdrawal is completed.
        if self.user and not self.pk and hasattr(self.user, 'wallet'):
            wallet = self.user.wallet
            if self.amount > wallet.balance:
                raise ValidationError({'amount': f'Insufficient balance. Your balance is ZMW {wallet.balance}'})
        
        # Security: Validate retry_count doesn't exceed max_retry_count
        if self.retry_count > self.max_retry_count:
            raise ValidationError({
                'retry_count': f'Retry count ({self.retry_count}) cannot exceed maximum retry count ({self.max_retry_count})'
            })
        
        # Security: Validate daily withdrawal limit (only for new withdrawals, not updates)
        if self.user and not self.pk:  # Only check for new withdrawals
            from django.utils import timezone
            from django.db.models import Sum
            from datetime import timedelta
            
            today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
            today_withdrawals = Withdrawal.objects.filter(
                user=self.user,
                status__in=['PENDING', 'PROCESSING', 'COMPLETED'],
                created_at__gte=today_start
            )
            
            today_total = today_withdrawals.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
            new_total = today_total + self.amount
            
            # Check global daily limit
            if new_total > self.DAILY_WITHDRAWAL_LIMIT:
                remaining = self.DAILY_WITHDRAWAL_LIMIT - today_total
                raise ValidationError({
                    'amount': f'Daily withdrawal limit exceeded. Maximum daily limit is ZMW {self.DAILY_WITHDRAWAL_LIMIT}. '
                             f'You have ZMW {remaining:.2f} remaining today.'
                })
            
            # Check per-payment-method daily limit
            if self.payment_method in self.PAYMENT_METHOD_LIMITS:
                method_limits = self.PAYMENT_METHOD_LIMITS[self.payment_method]
                method_today_withdrawals = today_withdrawals.filter(payment_method=self.payment_method)
                method_today_total = method_today_withdrawals.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
                method_new_total = method_today_total + self.amount
                
                if method_new_total > method_limits['daily']:
                    method_remaining = method_limits['daily'] - method_today_total
                    raise ValidationError({
                        'amount': f'Daily withdrawal limit for {self.get_payment_method_display()} exceeded. '
                                 f'Maximum daily limit is ZMW {method_limits["daily"]}. '
                                 f'You have ZMW {method_remaining:.2f} remaining today.'
                    })
        
        # Security: Validate status transitions (prevent invalid state changes)
        if self.pk:  # Only validate transitions for existing withdrawals
            old_instance = Withdrawal.objects.get(pk=self.pk)
            old_status = old_instance.status
            
            # Cannot change from COMPLETED, FAILED, or CANCELLED
            if old_status in ['COMPLETED', 'FAILED', 'CANCELLED']:
                if self.status != old_status:
                    raise ValidationError(
                        {'status': f'Cannot change status from {old_status} to {self.status}'}
                    )
            
            # Security: Cannot change amount after creation
            if self.amount != old_instance.amount:
                raise ValidationError({'amount': 'Cannot modify withdrawal amount after creation'})
            
            # Security: Cannot change user after creation
            if self.user_id != old_instance.user_id:
                raise ValidationError({'user': 'Cannot change withdrawal user after creation'})
    
    def save(self, *args, **kwargs):
        """Security: Run validation and auto-link wallet"""
        # Run full validation
        self.full_clean()
        
        # Automatically link to user's wallet if not set
        if not self.wallet:
            self.wallet = self.user.wallet
        
        super().save(*args, **kwargs)
    
    @property
    def can_be_cancelled(self):
        """Security: Check if withdrawal can be cancelled"""
        return self.status in ['PENDING', 'PROCESSING']
    
    @property
    def is_completed(self):
        """Check if withdrawal is completed"""
        return self.status == 'COMPLETED'
    
    @property
    def is_final(self):
        """Security: Check if withdrawal is in a final state (cannot be changed)"""
        return self.status in ['COMPLETED', 'FAILED', 'CANCELLED']

class SavedPaymentMethod(models.Model):
    """
    Model to store user's saved payment methods for quick access.
    
    Security features:
    - User ownership validation
    - Masked sensitive data display
    - Encrypted storage (can be enhanced with django-cryptography)
    - Default method selection
    """
    
    PAYMENT_METHOD_TYPES = [
        ('BANK_TRANSFER', 'Bank Transfer'),
        ('MOBILE_MONEY', 'Mobile Money'),
        # Legacy values (kept to avoid breaking existing rows / admin edits)
        ('ZYNELPAY', 'Zynel Pay (legacy)'),
        ('PAYPAL', 'PayPal (legacy)'),
        ('STRIPE', 'Stripe Card (legacy)'),
        ('OTHER', 'Other'),
    ]
    
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='saved_payment_methods')
    payment_method_type = models.CharField(max_length=20, choices=PAYMENT_METHOD_TYPES)
    label = models.CharField(max_length=100, help_text='User-friendly label (e.g., "My Main Bank Account", "Visa ending in 1234")')
    
    # Encrypted/masked account details
    # For cards: last 4 digits, expiry
    # For bank accounts: account number (masked)
    # For mobile money: phone number (masked)
    account_details = models.TextField(help_text='Account information (stored securely)')
    
    # Additional metadata (JSON field for flexibility)
    metadata = models.JSONField(default=dict, blank=True, help_text='Additional payment method details (e.g., bank name, card type)')
    
    # Gateway-specific identifiers (e.g., Paystack recipient code, Stripe customer ID)
    gateway_identifier = models.CharField(max_length=255, blank=True, null=True, help_text='Payment gateway identifier for this method')
    
    # Default method flag
    is_default = models.BooleanField(default=False, help_text='Use this as default payment method')
    
    # Status
    is_active = models.BooleanField(default=True, help_text='Whether this payment method is active')
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-is_default', '-created_at']
        verbose_name = 'Saved Payment Method'
        verbose_name_plural = 'Saved Payment Methods'
        indexes = [
            models.Index(fields=['user', 'is_active']),
            models.Index(fields=['user', 'is_default']),
        ]
        constraints = [
            # Security: Only one default method per user per payment type
            models.UniqueConstraint(
                fields=['user', 'payment_method_type'],
                condition=models.Q(is_default=True, is_active=True),
                name='unique_default_payment_method_per_type'
            ),
        ]
    
    def __str__(self):
        return f"{self.label} - {self.get_payment_method_type_display()} ({self.user.username})"
    
    def clean(self):
        """Security: Validate payment method data"""
        from django.core.exceptions import ValidationError
        
        # Validate label is provided
        if not self.label or not self.label.strip():
            raise ValidationError({'label': 'Label is required for saved payment method'})
        
        # Validate account details are provided
        if not self.account_details or not self.account_details.strip():
            raise ValidationError({'account_details': 'Account details are required'})
        
        # Security: If setting as default, unset other defaults of same type
        if self.is_default and self.is_active:
            # This will be handled in save() method
            pass
    
    def save(self, *args, **kwargs):
        """Security: Ensure only one default method per type per user"""
        # Run validation
        self.full_clean()
        
        # If setting as default, unset other defaults of same type
        if self.is_default and self.is_active:
            SavedPaymentMethod.objects.filter(
                user=self.user,
                payment_method_type=self.payment_method_type,
                is_default=True,
                is_active=True
            ).exclude(pk=self.pk if self.pk else None).update(is_default=False)
        
        super().save(*args, **kwargs)
    
    def mask_account_details(self):
        """
        Security: Return masked account details for display.
        Only shows last 4 digits/chars for security.
        """
        if not self.account_details:
            return "N/A"
        
        details = self.account_details.strip()
        
        # Mask based on payment method type
        if self.payment_method_type in ['STRIPE', 'PAYPAL']:
            # For cards: show last 4 digits
            if len(details) > 4:
                return f"****{details[-4:]}"
            return "****"
        elif self.payment_method_type == 'MOBILE_MONEY':
            # For phone numbers: show last 4 digits
            if len(details) > 4:
                return f"****{details[-4:]}"
            return "****"
        elif self.payment_method_type == 'BANK_TRANSFER':
            # For bank accounts: show last 4 digits
            if len(details) > 4:
                return f"****{details[-4:]}"
            return "****"
        else:
            # Generic masking
            if len(details) > 4:
                return f"****{details[-4:]}"
            return "****"
    
    @property
    def display_name(self):
        """Get display name for the payment method"""
        masked = self.mask_account_details()
        return f"{self.label} ({masked})"



# Create a wallet when a user is created
@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_wallet(sender, instance, created, **kwargs):
    if created:
        Wallet.objects.create(user=instance)


@receiver(post_save, sender=Transaction)
def audit_wallet_balance_change(sender, instance, created, **kwargs):
    """
    Audit log for all wallet balance changes driven by Transaction records.

    This runs whenever a new Transaction is created and records:
    - old_balance (derived as new_balance - amount)
    - new_balance (current wallet.balance)
    - delta (the transaction amount)

    It uses audit.utils.log_action and never raises, to avoid breaking main flow.
    """
    if not created:
        return

    wallet = instance.wallet
    logger = logging.getLogger(__name__)

    try:
        # Current balance after applying this transaction
        new_balance = wallet.balance

        # Derive old balance assuming Transaction.amount matches the balance change
        old_balance = None
        if new_balance is not None and instance.amount is not None:
            try:
                old_balance = new_balance - instance.amount
            except Exception:
                old_balance = None

        # Import here to avoid circular imports at module load time
        from audit.utils import log_action

        log_action(
            action='wallet_balance_changed',
            user=wallet.user if hasattr(wallet, 'user') else None,
            details={
                'wallet_id': wallet.id,
                'user_id': wallet.user.id if hasattr(wallet, 'user') and wallet.user else None,
                'transaction_id': instance.id,
                'transaction_type': instance.transaction_type,
                'amount': str(instance.amount),
                'old_balance': str(old_balance) if old_balance is not None else None,
                'new_balance': str(new_balance) if new_balance is not None else None,
                'delta': str(instance.amount),
                'description': instance.description,
            },
        )
    except Exception as e:
        logger.error(
            f"Failed to create wallet balance audit log for transaction {instance.id}: {e}",
            exc_info=True,
        )
