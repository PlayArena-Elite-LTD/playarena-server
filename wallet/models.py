from django.db import models
from django.conf import settings
from django.db.models.signals import post_save
from django.db.models import Sum
from django.dispatch import receiver
from django.core.exceptions import ValidationError
from decimal import Decimal
import json
import hashlib
import hmac

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
    """Model to track user deposits with payment gateway integration and security features"""
    
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PROCESSING', 'Processing'),
        ('COMPLETED', 'Completed'),
        ('FAILED', 'Failed'),
        ('CANCELLED', 'Cancelled'),
    ]
    
    PAYMENT_METHOD_CHOICES = [
        ('FLUTTERWAVE', 'Flutterwave'),
        ('PAYSTACK', 'Paystack'),
        ('PAYPAL', 'PayPal'),
        ('MOBILE_MONEY', 'Mobile Money'),
        ('BANK_TRANSFER', 'Bank Transfer'),
        ('OTHER', 'Other'),
    ]
    
    MAX_DEPOSIT_AMOUNT = Decimal('10000.00')
    MIN_DEPOSIT_AMOUNT = Decimal('1.00')
    MAX_RETRY_COUNT = 3
    
    # Basic fields
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='deposits')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES)
    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name='deposits', null=True, blank=True)
    
    # Payment gateway tracking fields (security-focused)
    payment_provider = models.CharField(
        max_length=20, 
        choices=[('PAYSTACK', 'Paystack'), ('FLUTTERWAVE', 'Flutterwave')],
        blank=True, 
        null=True,
        help_text='Payment gateway provider used'
    )
    payment_reference = models.CharField(
        max_length=255, 
        unique=True, 
        blank=True, 
        null=True,
        db_index=True,
        help_text='Unique payment reference (prevents duplicate payments)'
    )
    transaction_id = models.CharField(
        max_length=255, 
        blank=True, 
        null=True, 
        db_index=True,
        help_text='Payment gateway transaction ID'
    )
    gateway_transaction_id = models.CharField(
        max_length=255, 
        blank=True, 
        null=True,
        help_text='Additional gateway transaction identifier (e.g., flw_ref for Flutterwave)'
    )
    
    # Security and audit fields
    ip_address = models.GenericIPAddressField(
        blank=True, 
        null=True,
        help_text='IP address of the user when deposit was initiated (for fraud detection)'
    )
    user_agent = models.CharField(
        max_length=500, 
        blank=True, 
        null=True,
        help_text='User agent string (for security tracking)'
    )
    verification_hash = models.CharField(
        max_length=64, 
        blank=True, 
        null=True,
        help_text='SHA256 hash of payment data to prevent tampering'
    )
    webhook_signature = models.CharField(
        max_length=255, 
        blank=True, 
        null=True,
        help_text='Webhook signature for verification'
    )
    
    # Payment response and error tracking
    gateway_response = models.JSONField(
        default=dict, 
        blank=True,
        help_text='Full gateway response stored as JSON (for audit and debugging)'
    )
    failure_reason = models.TextField(
        blank=True, 
        null=True,
        help_text='Reason for payment failure (if applicable)'
    )
    retry_count = models.PositiveIntegerField(
        default=0,
        help_text='Number of retry attempts (prevents infinite retries)'
    )
    
    # Webhook tracking
    last_webhook_at = models.DateTimeField(
        blank=True, 
        null=True,
        help_text='Timestamp of last webhook received'
    )
    webhook_verified = models.BooleanField(
        default=False,
        help_text='Whether webhook signature was verified'
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(
        blank=True, 
        null=True,
        help_text='Timestamp when payment was completed'
    )
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['status']),
            models.Index(fields=['payment_reference']),
            models.Index(fields=['transaction_id']),
            models.Index(fields=['payment_provider', 'status']),
            models.Index(fields=['ip_address', 'created_at']),  # For fraud detection queries
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['payment_reference'],
                condition=models.Q(payment_reference__isnull=False),
                name='unique_deposit_payment_reference'
            ),
        ]
        verbose_name = 'Deposit'
        verbose_name_plural = 'Deposits'
    
    def clean(self):
        """Enhanced validation with security checks"""
        if self.amount <= 0:
            raise ValidationError({'amount': 'Deposit amount must be positive'})
        if self.amount < self.MIN_DEPOSIT_AMOUNT:
            raise ValidationError({'amount': f'Minimum deposit amount is ${self.MIN_DEPOSIT_AMOUNT}'})
        if self.amount > self.MAX_DEPOSIT_AMOUNT:
            raise ValidationError({'amount': f'Maximum deposit amount is ${self.MAX_DEPOSIT_AMOUNT}'})
        
        # Validate retry count
        if self.retry_count > self.MAX_RETRY_COUNT:
            raise ValidationError({'retry_count': f'Maximum retry count ({self.MAX_RETRY_COUNT}) exceeded'})
        
        # Validate payment provider matches payment method
        if self.payment_provider:
            if self.payment_method == 'PAYSTACK' and self.payment_provider != 'PAYSTACK':
                raise ValidationError({'payment_provider': 'Payment provider must match payment method'})
            if self.payment_method == 'FLUTTERWAVE' and self.payment_provider != 'FLUTTERWAVE':
                raise ValidationError({'payment_provider': 'Payment provider must match payment method'})
    
    def generate_verification_hash(self):
        """Generate SHA256 hash of critical payment data to prevent tampering"""
        data_string = f"{self.user.id}|{self.amount}|{self.payment_method}|{self.payment_reference or ''}|{self.created_at.isoformat() if self.created_at else ''}"
        return hashlib.sha256(data_string.encode('utf-8')).hexdigest()
    
    def verify_hash(self):
        """Verify that the payment data hasn't been tampered with"""
        if not self.verification_hash:
            return False
        expected_hash = self.generate_verification_hash()
        return hmac.compare_digest(self.verification_hash, expected_hash)
    
    def can_retry(self):
        """Check if deposit can be retried (security: prevent infinite retries)"""
        return self.retry_count < self.MAX_RETRY_COUNT and self.status in ['FAILED', 'PENDING']
    
    def mark_completed(self):
        """Securely mark deposit as completed with timestamp"""
        from django.utils import timezone
        self.status = 'COMPLETED'
        self.completed_at = timezone.now()
        if not self.verification_hash:
            self.verification_hash = self.generate_verification_hash()
        self.save(update_fields=['status', 'completed_at', 'verification_hash'])
    
    def increment_retry(self):
        """Increment retry count (with security limit)"""
        if self.can_retry():
            self.retry_count += 1
            self.save(update_fields=['retry_count'])
            return True
        return False
    
    def save(self, *args, **kwargs):
        """Enhanced save with security features"""
        # Auto-set wallet if not set
        if not self.wallet:
            self.wallet = self.user.wallet
        
        # Auto-set payment provider based on payment method
        if not self.payment_provider:
            if self.payment_method == 'PAYSTACK':
                self.payment_provider = 'PAYSTACK'
            elif self.payment_method == 'FLUTTERWAVE':
                self.payment_provider = 'FLUTTERWAVE'
        
        # Generate verification hash on first save if not exists
        if not self.verification_hash and self.pk:
            self.verification_hash = self.generate_verification_hash()
        
        # Full validation
        self.full_clean()
        super().save(*args, **kwargs)
    
    @property
    def is_completed(self):
        """Check if deposit is completed"""
        return self.status == 'COMPLETED'
    
    @property
    def is_secure(self):
        """Check if deposit has security features enabled"""
        return bool(self.verification_hash and self.ip_address)
    
    @property
    def gateway_response_summary(self):
        """Get summary of gateway response (for display)"""
        if not self.gateway_response:
            return None
        try:
            return {
                'status': self.gateway_response.get('status'),
                'message': self.gateway_response.get('message'),
                'gateway': self.payment_provider,
            }
        except:
            return None
    
    def __str__(self):
        return f"Deposit ${self.amount} - {self.get_status_display()} - {self.user.username} - {self.payment_reference or 'No Ref'}"


class Withdrawal(models.Model):
    """Model to track user withdrawals with payment gateway integration"""
    
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PROCESSING', 'Processing'),
        ('COMPLETED', 'Completed'),
        ('FAILED', 'Failed'),
        ('CANCELLED', 'Cancelled'),
    ]
    
    PAYMENT_METHOD_CHOICES = [
        ('FLUTTERWAVE', 'Flutterwave'),
        ('PAYSTACK', 'Paystack'),
        ('BANK_TRANSFER', 'Bank Transfer'),
        ('MOBILE_MONEY', 'Mobile Money'),
        ('PAYPAL', 'PayPal'),
        ('OTHER', 'Other'),
    ]
    
    MIN_WITHDRAWAL_AMOUNT = Decimal('1.00')
    MAX_WITHDRAWAL_AMOUNT = Decimal('5000.00')  # Maximum single withdrawal amount
    MAX_DAILY_WITHDRAWAL_AMOUNT = Decimal('10000.00')  # Maximum total withdrawals per day
    MAX_DAILY_WITHDRAWAL_COUNT = 5  # Maximum number of withdrawals per day
    
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
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['status']),
        ]
    
    def clean(self):
        from django.core.exceptions import ValidationError
        from django.utils import timezone
        from datetime import timedelta
        
        if self.amount <= 0:
            raise ValidationError({'amount': 'Withdrawal amount must be positive'})
        if self.amount < self.MIN_WITHDRAWAL_AMOUNT:
            raise ValidationError({'amount': f'Minimum withdrawal amount is ${self.MIN_WITHDRAWAL_AMOUNT}'})
        if self.amount > self.MAX_WITHDRAWAL_AMOUNT:
            raise ValidationError({'amount': f'Maximum withdrawal amount is ${self.MAX_WITHDRAWAL_AMOUNT}'})
        if not self.account_details or not self.account_details.strip():
            raise ValidationError({'account_details': 'Account details are required for withdrawal'})
        
        if self.user and hasattr(self.user, 'wallet'):
            wallet = self.user.wallet
            if self.amount > wallet.balance:
                raise ValidationError({'amount': f'Insufficient balance. Your balance is ${wallet.balance}'})
            
            # Security: Check daily withdrawal limits (only for new withdrawals, not updates)
            if not self.pk:  # Only check for new withdrawals
                now = timezone.now()
                today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
                
                # Get today's withdrawals (excluding this one if it exists)
                today_withdrawals = Withdrawal.objects.filter(
                    user=self.user,
                    created_at__gte=today_start,
                    status__in=['PENDING', 'PROCESSING', 'COMPLETED']
                )
                if self.pk:
                    today_withdrawals = today_withdrawals.exclude(id=self.pk)
                
                # Check daily withdrawal count limit
                today_count = today_withdrawals.count()
                if today_count >= self.MAX_DAILY_WITHDRAWAL_COUNT:
                    raise ValidationError({
                        'amount': f'Daily withdrawal limit reached. Maximum {self.MAX_DAILY_WITHDRAWAL_COUNT} withdrawals per day.'
                    })
                
                # Check daily withdrawal amount limit
                today_total = today_withdrawals.aggregate(
                    total=Sum('amount')
                )['total'] or Decimal('0.00')
                
                if (today_total + self.amount) > self.MAX_DAILY_WITHDRAWAL_AMOUNT:
                    remaining = self.MAX_DAILY_WITHDRAWAL_AMOUNT - today_total
                    raise ValidationError({
                        'amount': f'Daily withdrawal amount limit exceeded. Maximum ${self.MAX_DAILY_WITHDRAWAL_AMOUNT} per day. You can withdraw up to ${remaining:.2f} more today.'
                    })
    
    def save(self, *args, **kwargs):
        self.full_clean()
        if not self.wallet:
            self.wallet = self.user.wallet
        super().save(*args, **kwargs)
    
    @property
    def is_completed(self):
        return self.status == 'COMPLETED'
    
    def __str__(self):
        return f"Withdrawal ${self.amount} - {self.get_status_display()} - {self.user.username}"


# Create a wallet when a user is created
@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_wallet(sender, instance, created, **kwargs):
    if created:
        Wallet.objects.create(user=instance)