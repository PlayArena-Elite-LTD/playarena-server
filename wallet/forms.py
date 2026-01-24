from django import forms
from decimal import Decimal


class DepositForm(forms.Form):
    """Form for depositing funds into wallet"""
    
    PAYMENT_METHODS = [
        ('FLUTTERWAVE', 'Flutterwave'),
        ('PAYSTACK', 'Paystack'),
        ('PAYPAL', 'PayPal'),
        ('MOBILE_MONEY', 'Mobile Money'),
        ('BANK_TRANSFER', 'Bank Transfer'),
        ('OTHER', 'Other'),
    ]
    
    amount = forms.DecimalField(
        label='Amount',
        max_digits=10,
        decimal_places=2,
        min_value=Decimal('1.00'),
        max_value=Decimal('10000.00'),
        help_text='Enter amount between $1.00 and $10,000.00',
        widget=forms.NumberInput(attrs={
            'class': 'form-input',
            'placeholder': '0.00',
            'step': '0.01',
            'min': '1',
            'max': '10000'
        })
    )
    
    payment_method = forms.ChoiceField(
        label='Payment Method',
        choices=PAYMENT_METHODS,
        widget=forms.Select(attrs={
            'class': 'form-select'
        })
    )
    
    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
    
    def clean_amount(self):
        """Additional validation for amount"""
        amount = self.cleaned_data.get('amount')
        if amount is not None:
            if amount <= 0:
                raise forms.ValidationError("Deposit amount must be greater than zero.")
            if amount > 10000:
                raise forms.ValidationError("Deposit amount cannot exceed $10,000.")
        return amount


class WithdrawalForm(forms.Form):
    """Form for withdrawing funds from wallet"""
    
    PAYMENT_METHODS = [
        ('FLUTTERWAVE', 'Flutterwave'),
        ('PAYSTACK', 'Paystack'),
        ('PAYPAL', 'PayPal'),
        ('MOBILE_MONEY', 'Mobile Money'),
        ('BANK_TRANSFER', 'Bank Transfer'),
        ('OTHER', 'Other'),
    ]
    
    amount = forms.DecimalField(
        label='Amount',
        max_digits=10,
        decimal_places=2,
        min_value=Decimal('1.00'),
        max_value=Decimal('5000.00'),
        help_text='Enter amount between $1.00 and $5,000.00',
        widget=forms.NumberInput(attrs={
            'class': 'form-input',
            'placeholder': '0.00',
            'step': '0.01',
            'min': '1',
            'max': '5000'
        })
    )
    
    payment_method = forms.ChoiceField(
        label='Payment Method',
        choices=PAYMENT_METHODS,
        widget=forms.Select(attrs={
            'class': 'form-select'
        })
    )
    
    account_details = forms.CharField(
        label='Account Details',
        widget=forms.Textarea(attrs={
            'class': 'form-textarea',
            'rows': 4,
            'placeholder': 'Enter your account details (bank account number, PayPal email, mobile money number, etc.)'
        }),
        help_text='Provide your account details for receiving the withdrawal',
        required=True
    )
    
    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
    
    def clean_amount(self):
        """Additional validation for amount, balance, and daily limits"""
        from django.utils import timezone
        from datetime import timedelta
        from .models import Withdrawal
        
        amount = self.cleaned_data.get('amount')
        if amount is not None:
            if amount <= 0:
                raise forms.ValidationError("Withdrawal amount must be greater than zero.")
            if amount > Withdrawal.MAX_WITHDRAWAL_AMOUNT:
                raise forms.ValidationError(f"Maximum withdrawal amount is ${Withdrawal.MAX_WITHDRAWAL_AMOUNT:.2f}")
            
            if self.user and hasattr(self.user, 'wallet'):
                wallet = self.user.wallet
                if amount > wallet.balance:
                    raise forms.ValidationError(f"Insufficient balance. Your balance is ${wallet.balance:.2f}")
                
                # Check daily withdrawal limits
                now = timezone.now()
                today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
                
                today_withdrawals = Withdrawal.objects.filter(
                    user=self.user,
                    created_at__gte=today_start,
                    status__in=['PENDING', 'PROCESSING', 'COMPLETED']
                )
                
                # Check daily withdrawal count limit
                today_count = today_withdrawals.count()
                if today_count >= Withdrawal.MAX_DAILY_WITHDRAWAL_COUNT:
                    raise forms.ValidationError(
                        f'Daily withdrawal limit reached. Maximum {Withdrawal.MAX_DAILY_WITHDRAWAL_COUNT} withdrawals per day.'
                    )
                
                # Check daily withdrawal amount limit
                from django.db.models import Sum
                today_total = today_withdrawals.aggregate(
                    total=Sum('amount')
                )['total'] or Decimal('0.00')
                
                if (today_total + amount) > Withdrawal.MAX_DAILY_WITHDRAWAL_AMOUNT:
                    remaining = Withdrawal.MAX_DAILY_WITHDRAWAL_AMOUNT - today_total
                    raise forms.ValidationError(
                        f'Daily withdrawal amount limit exceeded. Maximum ${Withdrawal.MAX_DAILY_WITHDRAWAL_AMOUNT:.2f} per day. '
                        f'You can withdraw up to ${remaining:.2f} more today.'
                    )
        return amount
    
    def clean_account_details(self):
        """Validate account details"""
        account_details = self.cleaned_data.get('account_details')
        if not account_details or len(account_details.strip()) < 5:
            raise forms.ValidationError("Please provide valid account details (at least 5 characters).")
        return account_details.strip()



