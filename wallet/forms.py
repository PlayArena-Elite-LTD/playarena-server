from django import forms
from decimal import Decimal


class DepositForm(forms.Form):
    """Form for depositing funds into wallet"""
    
    PAYMENT_METHODS = [
        ('STRIPE', 'Stripe'),
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
        ('STRIPE', 'Stripe'),
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
    
    def clean_amount(self):
        """Additional validation for amount"""
        amount = self.cleaned_data.get('amount')
        if amount is not None:
            if amount <= 0:
                raise forms.ValidationError("Withdrawal amount must be greater than zero.")
            if amount > 5000:
                raise forms.ValidationError("Withdrawal amount cannot exceed $5,000 per transaction.")
        return amount
    
    def clean_account_details(self):
        """Validate account details"""
        account_details = self.cleaned_data.get('account_details')
        if account_details and len(account_details.strip()) < 5:
            raise forms.ValidationError("Please provide valid account details (at least 5 characters).")
        return account_details



