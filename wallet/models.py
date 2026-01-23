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
    """Model to track user deposits with payment gateway integration"""
    
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
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['status']),
        ]
    
    def clean(self):
        from django.core.exceptions import ValidationError
        if self.amount <= 0:
            raise ValidationError({'amount': 'Deposit amount must be positive'})
        if self.amount < self.MIN_DEPOSIT_AMOUNT:
            raise ValidationError({'amount': f'Minimum deposit amount is ${self.MIN_DEPOSIT_AMOUNT}'})
        if self.amount > self.MAX_DEPOSIT_AMOUNT:
            raise ValidationError({'amount': f'Maximum deposit amount is ${self.MAX_DEPOSIT_AMOUNT}'})
    
    def save(self, *args, **kwargs):
        self.full_clean()
        if not self.wallet:
            self.wallet = self.user.wallet
        super().save(*args, **kwargs)
    
    @property
    def is_completed(self):
        return self.status == 'COMPLETED'
    
    def __str__(self):
        return f"Deposit ${self.amount} - {self.get_status_display()} - {self.user.username}"


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
        if self.amount <= 0:
            raise ValidationError({'amount': 'Withdrawal amount must be positive'})
        if self.amount < self.MIN_WITHDRAWAL_AMOUNT:
            raise ValidationError({'amount': f'Minimum withdrawal amount is ${self.MIN_WITHDRAWAL_AMOUNT}'})
        if not self.account_details or not self.account_details.strip():
            raise ValidationError({'account_details': 'Account details are required for withdrawal'})
        if self.user and hasattr(self.user, 'wallet'):
            wallet = self.user.wallet
            if self.amount > wallet.balance:
                raise ValidationError({'amount': f'Insufficient balance. Your balance is ${wallet.balance}'})
    
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