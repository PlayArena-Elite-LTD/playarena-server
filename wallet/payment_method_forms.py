"""
Forms for managing saved payment methods.
"""

from django import forms
from .models import SavedPaymentMethod


class SavedPaymentMethodForm(forms.ModelForm):
    """Form for creating/editing saved payment methods"""
    
    class Meta:
        model = SavedPaymentMethod
        fields = ['payment_method_type', 'label', 'account_details', 'is_default', 'metadata']
        widgets = {
            'payment_method_type': forms.Select(attrs={
                'class': 'form-select',
                'required': True
            }),
            'label': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., My Main Bank Account, Visa ending in 1234',
                'required': True
            }),
            'account_details': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Enter account details (account number, card number, phone number, etc.)',
                'required': True
            }),
            'is_default': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'metadata': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Optional: Additional details in JSON format (e.g., {"bank_name": "Chase", "account_type": "Checking"})'
            }),
        }
    
    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        # Set user if creating new
        if self.user and not self.instance.pk:
            self.instance.user = self.user
    
    def clean(self):
        """Security: Validate payment method data"""
        cleaned_data = super().clean()
        
        # Security: Ensure user owns this payment method
        if self.instance.pk and self.user:
            if self.instance.user != self.user:
                raise forms.ValidationError("You can only edit your own payment methods.")
        
        return cleaned_data


class DeletePaymentMethodForm(forms.Form):
    """Confirmation form for deleting payment methods"""
    
    confirm = forms.BooleanField(
        required=True,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input'
        }),
        label='I confirm I want to delete this payment method'
    )

