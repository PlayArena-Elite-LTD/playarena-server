from django import forms
from decimal import Decimal
from .models import Deposit, Withdrawal

class DepositForm(forms.Form):
    """Form for creating deposit requests"""
    
    amount = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=Decimal('1.00'),
        max_value=Decimal('10000.00'),
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter amount',
            'step': '0.01'
        }),
        label='Deposit Amount',
        help_text='Minimum: $1.00, Maximum: $10,000.00'
    )
    
    payment_method = forms.ChoiceField(
        choices=Deposit.PAYMENT_METHOD_CHOICES,
        widget=forms.Select(attrs={'class': 'form-control'}),
        label='Payment Method',
        initial='OTHER'
    )
    
    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
    def clean_amount(self):
        """Additional validation for deposit amount"""
        amount = self.cleaned_data.get('amount')
        
        if amount is None:
            return amount
            
        # Ensure amount is within bounds (DecimalField should handle this, but double-check)
        if amount < Decimal('1.00'):
            raise forms.ValidationError('Minimum deposit amount is $1.00')
        
        if amount > Decimal('10000.00'):
            raise forms.ValidationError('Maximum deposit amount is $10,000.00')
        
        return amount


class WithdrawalForm(forms.Form):
    """Form for creating withdrawal requests"""
    
    amount = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=Decimal('1.00'),
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter amount',
            'step': '0.01'
        }),
        label='Withdrawal Amount',
        help_text='Minimum: $1.00'
    )
    
    payment_method = forms.ChoiceField(
        choices=Withdrawal.PAYMENT_METHOD_CHOICES,
        widget=forms.Select(attrs={'class': 'form-control'}),
        label='Payment Method',
        initial='BANK_TRANSFER'
    )
    
    account_details = forms.CharField(
        max_length=500,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'placeholder': 'Enter account details (account number, mobile number, etc.)',
            'rows': 4
        }),
        label='Account Details',
        help_text='Required: Provide account information for withdrawal (account number, mobile number, email, etc.)'
    )
    
    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
    def clean_amount(self):
        """Validate withdrawal amount and check balance"""
        amount = self.cleaned_data.get('amount')
        
        if amount is None:
            return amount
            
        # Ensure amount meets minimum
        if amount < Decimal('1.00'):
            raise forms.ValidationError('Minimum withdrawal amount is $1.00')
        
        # Check user has sufficient balance
        if self.user and hasattr(self.user, 'wallet'):
            wallet = self.user.wallet
            if amount > wallet.balance:
                raise forms.ValidationError(
                    f'Insufficient balance. Your balance is ${wallet.balance:.2f}'
                )
        
        return amount
    
    def clean_account_details(self):
        """Validate account details are provided"""
        account_details = self.cleaned_data.get('account_details')
        
        if not account_details or not account_details.strip():
            raise forms.ValidationError('Account details are required for withdrawal')
        
        return account_details.strip()
