from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from .models import Match, Evidence
from .utils import validate_evidence_file, validate_file_size, validate_file_type

class MatchCreationForm(forms.ModelForm):
    class Meta:
        model = Match
        fields = ['game', 'device', 'privacy', 'amount']
        widgets = {
            'game': forms.Select(attrs={'class': 'form-control'}),
            'device': forms.Select(attrs={'class': 'form-control'}),
            'privacy': forms.Select(attrs={'class': 'form-control'}),
            'amount': forms.Select(attrs={'class': 'form-control'}),
        }
        
    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        # Custom labels
        self.fields['game'].label = "Select Game"
        self.fields['device'].label = "Gaming Platform"
        self.fields['privacy'].label = "Match Privacy"
        self.fields['amount'].label = "Stake Amount"
        
        # Help texts
        self.fields['privacy'].help_text = "Private matches require a code to join"
        self.fields['amount'].help_text = "Amount each player contributes to the prize pool"
        
    def clean_amount(self):
        """Validate that user has enough balance for the match"""
        amount = self.cleaned_data.get('amount')
        
        if self.user and hasattr(self.user, 'wallet'):
            if self.user.wallet.balance < amount:
                raise forms.ValidationError(
                    f"Insufficient funds. Your balance (${self.user.wallet.balance}) is less than the match amount (${amount})."
                )
        
        return amount
    
    def save(self, commit=True):
        match = super().save(commit=False)
        
        if self.user:
            match.creator = self.user
            
        if commit:
            match.save()
            
        return match


class JoinMatchForm(forms.Form):
    joining_code = forms.CharField(
        max_length=10, 
        label="Match Code",
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter 10-character code'})
    )
    
    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
    
    def clean_joining_code(self):
        code = self.cleaned_data.get('joining_code')
        
        try:
            match = Match.objects.get(joining_code=code, status='OPEN')
            
            # Check if user is trying to join their own match
            if match.creator == self.user:
                raise forms.ValidationError("You cannot join your own match.")
                
            # Check if user has sufficient balance
            if self.user and hasattr(self.user, 'wallet'):
                if self.user.wallet.balance < match.amount:
                    raise forms.ValidationError(
                        f"Insufficient funds. Your balance (${self.user.wallet.balance}) is less than the match amount (${match.amount})."
                    )
                    
        except Match.DoesNotExist:
            raise forms.ValidationError("Invalid match code or the match is no longer available.")
            
        return code


class EvidenceUploadForm(forms.Form):
    """
    Form for uploading evidence files (screenshots/videos) for match results.
    
    Security features:
    - File type validation (images/videos only)
    - File size limits (10MB images, 50MB videos)
    - MIME type validation
    """
    
    file = forms.FileField(
        label="Evidence File",
        help_text="Upload a screenshot or video (Max 10MB for images, 50MB for videos)"
    )
    file_type = forms.ChoiceField(
        choices=Evidence.FILE_TYPE_CHOICES,
        label="File Type",
        help_text="Select whether this is an image or video"
    )
    description = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
        label="Description (Optional)",
        help_text="Optional description of the evidence"
    )
    
    def __init__(self, *args, **kwargs):
        self.match = kwargs.pop('match', None)
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
    
    def clean_file(self):
        """Security: Validate file type and size using utility functions"""
        file = self.cleaned_data.get('file')
        
        if not file:
            raise ValidationError("Please select a file to upload.")
        
        # Get file type from form data (may not be cleaned yet, so get from initial data)
        file_type = self.cleaned_data.get('file_type') or self.data.get('file_type')
        
        if not file_type:
            raise ValidationError("Please select a file type.")
        
        # Use utility functions for validation
        try:
            validate_file_size(file, file_type)
            validate_file_type(file, file_type)
        except ValidationError as e:
            # Re-raise validation errors
            raise e
        
        return file
    
    def clean(self):
        """Additional validation"""
        cleaned_data = super().clean()
        file = cleaned_data.get('file')
        file_type = cleaned_data.get('file_type')
        
        # Ensure file and file_type are both provided
        if file and not file_type:
            raise ValidationError("Please select a file type.")
        
        return cleaned_data
