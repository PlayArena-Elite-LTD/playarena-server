from django.db import models
from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver
from decimal import Decimal

class Wallet(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='wallet')
    balance = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    
class Transaction(models.Model):
    TRANSACTION_TYPES = [
        ('DEPOSIT', 'Deposit'),
        ('WITHDRAWAL', 'Withdrawal'),
        ('MATCH_CREATION', 'Match Creation'),
        ('MATCH_JOINING', 'Match Joining'),
        ('MATCH_WINNINGS', 'Match Winnings'),
        ('MATCH_REFUND', 'Match Refund'),
        ('MATCH_DRAW_RETURN', 'Match Draw Return'),
        ('OTHER', 'Other'),
    ]
    
    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name='transactions')
    amount = models.DecimalField(max_digits=10, decimal_places=2)  # Positive for credits, negative for debits
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)
    description = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    related_match = models.ForeignKey('matches.Match', on_delete=models.SET_NULL, null=True, blank=True)
    
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
    
    PAYMENT_METHOD_CHOICES = [
        ('STRIPE', 'Stripe'),
        ('PAYPAL', 'PayPal'),
        ('MOBILE_MONEY', 'Mobile Money'),
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
        return f"Deposit ${self.amount} - {self.get_status_display()} - {self.user.username}"
    
    def clean(self):
        """Security: Validate deposit amount and business rules"""
        from django.core.exceptions import ValidationError
        
        # Validate amount is positive
        if self.amount <= 0:
            raise ValidationError({'amount': 'Deposit amount must be positive'})
        
        # Validate minimum deposit amount
        if self.amount < self.MIN_DEPOSIT_AMOUNT:
            raise ValidationError({'amount': f'Minimum deposit amount is ${self.MIN_DEPOSIT_AMOUNT}'})
        
        # Validate maximum deposit amount
        if self.amount > self.MAX_DEPOSIT_AMOUNT:
            raise ValidationError({'amount': f'Maximum deposit amount is ${self.MAX_DEPOSIT_AMOUNT}'})
        
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
        ('PAYPAL', 'PayPal'),
        ('STRIPE', 'Stripe'),
        ('OTHER', 'Other'),
    ]
    
    # Security: Minimum withdrawal amount (no maximum - users can withdraw any positive amount)
    MIN_WITHDRAWAL_AMOUNT = Decimal('1.00')  # Match deposit minimum for consistency
    
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='withdrawals')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES)
    account_details = models.TextField(help_text='Account information for withdrawal (account number, mobile number, etc.)')
    transaction_id = models.CharField(max_length=255, blank=True, null=True, help_text='Payment gateway transaction ID')
    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name='withdrawals', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Withdrawal'
        verbose_name_plural = 'Withdrawals'
        # Security: Add index for faster queries
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['status']),
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
        return f"Withdrawal ${self.amount} - {self.get_status_display()} - {self.user.username}"
    
    def clean(self):
        """Security: Validate withdrawal amount and business rules"""
        from django.core.exceptions import ValidationError
        
        # Validate amount is positive
        if self.amount <= 0:
            raise ValidationError({'amount': 'Withdrawal amount must be positive'})
        
        # Validate minimum withdrawal amount
        if self.amount < self.MIN_WITHDRAWAL_AMOUNT:
            raise ValidationError({'amount': f'Minimum withdrawal amount is ${self.MIN_WITHDRAWAL_AMOUNT}'})
        
        # Security: Validate account details are provided
        if not self.account_details or not self.account_details.strip():
            raise ValidationError({'account_details': 'Account details are required for withdrawal'})
        
        # Security: Validate balance if user and wallet are set
        if self.user and hasattr(self.user, 'wallet'):
            wallet = self.user.wallet
            if self.amount > wallet.balance:
                raise ValidationError({'amount': f'Insufficient balance. Your balance is ${wallet.balance}'})
        
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

# Create a wallet when a user is created
@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_wallet(sender, instance, created, **kwargs):
    if created:
        Wallet.objects.create(user=instance)