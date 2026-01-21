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
