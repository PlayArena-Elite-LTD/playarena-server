from django import forms
from decimal import Decimal
from .models import SavedPaymentMethod
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
    
    use_saved_method = forms.BooleanField(
        required=False,
        initial=False,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input'
        }),
        label='Use saved payment method'
    )
    
    saved_payment_method = forms.ModelChoiceField(
        queryset=SavedPaymentMethod.objects.none(),
        required=False,
        widget=forms.Select(attrs={
            'class': 'form-control'
        }),
        label='Select Saved Payment Method'
    )
    
    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        # Populate saved payment methods for this user
        if self.user:
            saved_methods = SavedPaymentMethod.objects.filter(
                user=self.user,
                is_active=True,
                payment_method_type__in=[choice[0] for choice in Withdrawal.PAYMENT_METHOD_CHOICES]
            ).order_by('-is_default', '-created_at')
            
            self.fields['saved_payment_method'].queryset = saved_methods
            
            # Set default saved method if available
            default_method = saved_methods.filter(is_default=True).first()
            if default_method:
                self.fields['saved_payment_method'].initial = default_method
                self.fields['use_saved_method'].initial = True
                self.fields['payment_method'].initial = default_method.payment_method_type
    
    def clean(self):
        """Validate form data"""
        cleaned_data = super().clean()
        use_saved = cleaned_data.get('use_saved_method', False)
        saved_method = cleaned_data.get('saved_payment_method')
        account_details = cleaned_data.get('account_details', '')
        
        # If using saved method, validate it exists and is active
        if use_saved:
            if not saved_method:
                raise forms.ValidationError('Please select a saved payment method.')
            if not saved_method.is_active:
                raise forms.ValidationError('Selected payment method is not active.')
            # Set account_details from saved method
            cleaned_data['account_details'] = saved_method.account_details
            cleaned_data['payment_method'] = saved_method.payment_method_type
        else:
            # If not using saved method, account_details is required
            if not account_details or not account_details.strip():
                raise forms.ValidationError({
                    'account_details': 'Account details are required when not using a saved payment method.'
                })
            cleaned_data['account_details'] = account_details.strip()
        
        return cleaned_data
    
    def clean_account_details(self):
        """Validate account details are provided"""
        account_details = self.cleaned_data.get('account_details', '')
        use_saved = self.data.get('use_saved_method', False)
        
        # Only validate if not using saved method
        if not use_saved:
            if not account_details or not account_details.strip():
                raise forms.ValidationError('Account details are required for withdrawal')
            return account_details.strip()
        
        return account_details
