from django import forms
from decimal import Decimal
import re
from django.conf import settings
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
            'placeholder': '0.00',
            'step': '0.01',
            'inputmode': 'decimal',
        }),
        label='Deposit Amount',
        help_text='Minimum: $1.00, Maximum: $10,000.00'
    )
    
    payment_method = forms.ChoiceField(
        choices=Deposit.PAYMENT_METHOD_CHOICES,
        widget=forms.Select(attrs={'class': 'form-control'}),
        label='Payment Method',
        initial='LIPILA'
    )

    mobile_number = forms.CharField(
        max_length=20,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '260971234567',
            'autocomplete': 'tel',
        }),
        label='Mobile Money Number',
        help_text='Zambian mobile number, e.g. 260971234567',
    )
    
    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        choices = []
        lipila_mock = bool(getattr(settings, 'LIPILA_MOCK_MODE', False))
        lipila_ready = bool((getattr(settings, 'LIPILA_API_KEY', '') or '').strip())
        if lipila_ready or lipila_mock:
            choices.append(('LIPILA_MOMO', 'Lipila Mobile Money (MoMo)'))
            choices.append(('LIPILA', 'Lipila (Card)'))
        choices.append(('BANK_TRANSFER', 'Bank Transfer'))
        self.fields['payment_method'].choices = choices

        if lipila_ready or lipila_mock:
            self.fields['payment_method'].initial = 'LIPILA_MOMO'
        else:
            self.fields['payment_method'].initial = 'BANK_TRANSFER'
            self.fields['mobile_number'].widget = forms.HiddenInput()

        if not lipila_ready and not lipila_mock:
            self.fields['mobile_number'].widget = forms.HiddenInput()

    def clean(self):
        cleaned = super().clean()
        method = cleaned.get('payment_method')
        mobile = (cleaned.get('mobile_number') or '').strip()
        if method == 'LIPILA_MOMO' and not mobile:
            self.add_error('mobile_number', 'Mobile number is required for Lipila Mobile Money deposits.')
        return cleaned
        
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

    MOBILE_PROVIDER_CHOICES = [
        ('', 'Select mobile network'),
        ('Airtel', 'Airtel Money'),
        ('MTN', 'MTN Mobile Money'),
    ]
    
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
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'placeholder': 'Bank account number and bank code',
            'rows': 4,
            'spellcheck': 'false',
        }),
        label='Bank Account Details',
        help_text='Required for bank withdrawals.'
    )

    mobile_provider = forms.ChoiceField(
        choices=MOBILE_PROVIDER_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'}),
        label='Mobile Network',
    )

    mobile_number = forms.CharField(
        max_length=24,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '097XXXXXXX or 26097XXXXXXX',
            'autocomplete': 'tel',
            'inputmode': 'tel',
        }),
        label='Mobile Money Number',
        help_text='Enter a Zambian number beginning with 0 or 260.',
    )
    
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
    
    def clean_amount(self):
        """Validate withdrawal amount, check balance, and enforce limits"""
        from django.utils import timezone
        from django.db.models import Sum
        from datetime import timedelta
        
        amount = self.cleaned_data.get('amount')
        payment_method = self.cleaned_data.get('payment_method')
        
        if amount is None:
            return amount
            
        # Ensure amount meets minimum
        if amount < Decimal('1.00'):
            raise forms.ValidationError('Minimum withdrawal amount is $1.00')
        
        # Check maximum withdrawal amount (global limit)
        if amount > Decimal('50000.00'):
            raise forms.ValidationError('Maximum withdrawal amount per transaction is $50,000.00')
        
        # Check per-payment-method limits
        payment_method_limits = {
            'BANK_TRANSFER': {'max': Decimal('50000.00'), 'daily': Decimal('100000.00')},
            'MOBILE_MONEY': {'max': Decimal('10000.00'), 'daily': Decimal('50000.00')},
            'OTHER': {'max': Decimal('10000.00'), 'daily': Decimal('25000.00')},
        }
        
        if payment_method and payment_method in payment_method_limits:
            method_limits = payment_method_limits[payment_method]
            if amount > method_limits['max']:
                method_display = dict(Withdrawal.PAYMENT_METHOD_CHOICES).get(payment_method, payment_method)
                raise forms.ValidationError(
                    f'Maximum withdrawal amount for {method_display} is ${method_limits["max"]}'
                )
        
        # Check user has sufficient balance
        if self.user and hasattr(self.user, 'wallet'):
            wallet = self.user.wallet
            if amount > wallet.balance:
                raise forms.ValidationError(
                    f'Insufficient balance. Your balance is ${wallet.balance:.2f}'
                )
        
        # Check daily withdrawal limits (only if user is set)
        if self.user:
            from wallet.models import Withdrawal
            
            today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
            today_withdrawals = Withdrawal.objects.filter(
                user=self.user,
                status__in=['PENDING', 'PROCESSING', 'COMPLETED'],
                created_at__gte=today_start
            )
            
            today_total = today_withdrawals.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
            new_total = today_total + amount
            
            # Check global daily limit
            if new_total > Decimal('100000.00'):
                remaining = Decimal('100000.00') - today_total
                raise forms.ValidationError(
                    f'Daily withdrawal limit exceeded. Maximum daily limit is $100,000.00. '
                    f'You have ${remaining:.2f} remaining today.'
                )
            
            # Check per-payment-method daily limit
            if payment_method and payment_method in payment_method_limits:
                method_limits = payment_method_limits[payment_method]
                method_today_withdrawals = today_withdrawals.filter(payment_method=payment_method)
                method_today_total = method_today_withdrawals.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
                method_new_total = method_today_total + amount
                
                if method_new_total > method_limits['daily']:
                    method_remaining = method_limits['daily'] - method_today_total
                    method_display = dict(Withdrawal.PAYMENT_METHOD_CHOICES).get(payment_method, payment_method)
                    raise forms.ValidationError(
                        f'Daily withdrawal limit for {method_display} exceeded. '
                        f'Maximum daily limit is ${method_limits["daily"]}. '
                        f'You have ${method_remaining:.2f} remaining today.'
                    )
        
        return amount
    
    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        # Show only active withdrawal methods for now.
        self.fields['payment_method'].choices = [
            ('BANK_TRANSFER', 'Bank Transfer'),
            ('MOBILE_MONEY', 'Mobile Money'),
        ]
        
        # Populate saved payment methods for this user
        if self.user:
            saved_methods = SavedPaymentMethod.objects.filter(
                user=self.user,
                is_active=True,
                payment_method_type__in=[choice[0] for choice in self.fields['payment_method'].choices]
            ).order_by('-is_default', '-created_at')
            
            self.fields['saved_payment_method'].queryset = saved_methods
            
            # Add data attributes to options for JavaScript
            for method in saved_methods:
                # This will be handled in the template via JavaScript
                pass
            
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
        payment_method = cleaned_data.get('payment_method')
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
        elif payment_method == 'MOBILE_MONEY':
            mobile_number = (cleaned_data.get('mobile_number') or '').strip()
            mobile_provider = (cleaned_data.get('mobile_provider') or '').strip()

            # Continue accepting the old phone|provider value for API clients
            # and already-rendered forms during deployment.
            if not mobile_number and account_details:
                legacy_parts = [part.strip() for part in account_details.split('|', 1)]
                mobile_number = legacy_parts[0]
                if not mobile_provider and len(legacy_parts) == 2:
                    provider_names = {'airtel': 'Airtel', 'mtn': 'MTN'}
                    mobile_provider = provider_names.get(legacy_parts[1].lower(), '')

            normalized_number = self._normalize_zambian_mobile_number(mobile_number)
            if not normalized_number:
                self.add_error(
                    'mobile_number',
                    'Enter a valid Zambian mobile number, e.g. 097XXXXXXX or 26097XXXXXXX.',
                )
            if mobile_provider not in {'Airtel', 'MTN'}:
                self.add_error('mobile_provider', 'Select Airtel or MTN.')

            if normalized_number and mobile_provider in {'Airtel', 'MTN'}:
                cleaned_data['mobile_number'] = normalized_number
                cleaned_data['mobile_provider'] = mobile_provider
                cleaned_data['account_details'] = f'{normalized_number}|{mobile_provider}'
        else:
            # Bank withdrawals retain the existing free-text account details.
            if not account_details or not account_details.strip():
                raise forms.ValidationError({
                    'account_details': 'Bank account details are required.'
                })
            cleaned_data['account_details'] = account_details.strip()
        
        return cleaned_data
    
    def clean_account_details(self):
        """Trim bank/legacy details; method-specific validation happens in clean()."""
        account_details = self.cleaned_data.get('account_details', '')
        return account_details.strip()

    @staticmethod
    def _normalize_zambian_mobile_number(value):
        digits = re.sub(r'\D', '', value or '')
        if digits.startswith('0') and len(digits) == 10:
            return '260' + digits[1:]
        if digits.startswith('260') and len(digits) == 12:
            return digits
        return None
