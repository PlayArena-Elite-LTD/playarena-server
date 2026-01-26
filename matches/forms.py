from django import forms
from django.core.exceptions import ValidationError
from .models import Match, Evidence
import os

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
    """Form for uploading evidence files (screenshots/videos) for matches"""
    
    # File size limits (in bytes)
    MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10MB
    MAX_VIDEO_SIZE = 50 * 1024 * 1024  # 50MB
    
    # Allowed file extensions
    ALLOWED_IMAGE_EXTENSIONS = ['.jpg', '.jpeg', '.png']
    ALLOWED_VIDEO_EXTENSIONS = ['.mp4', '.mov']
    
    evidence_file = forms.FileField(
        required=True,
        label="Evidence File",
        help_text="Upload a screenshot or video (Images: max 10MB, Videos: max 50MB)",
        widget=forms.FileInput(attrs={
            'class': 'form-control',
            'accept': 'image/jpeg,image/png,video/mp4,video/quicktime',
            'id': 'evidence-file-input'
        })
    )
    
    description = forms.CharField(
        required=False,
        max_length=500,
        label="Description (Optional)",
        help_text="Add a brief description of the evidence",
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'e.g., Screenshot showing final score, Video of match ending...'
        })
    )
    
    def clean_evidence_file(self):
        """Validate file size and type"""
        file = self.cleaned_data.get('evidence_file')
        
        if not file:
            raise ValidationError("Please select a file to upload.")
        
        # Get file extension
        file_name = file.name
        ext = os.path.splitext(file_name)[1].lower()
        
        # Check file extension
        if ext not in self.ALLOWED_IMAGE_EXTENSIONS + self.ALLOWED_VIDEO_EXTENSIONS:
            allowed = ', '.join(self.ALLOWED_IMAGE_EXTENSIONS + self.ALLOWED_VIDEO_EXTENSIONS)
            raise ValidationError(
                f"Unsupported file type. Allowed types: {allowed}"
            )
        
        # Check file size based on type
        if ext in self.ALLOWED_IMAGE_EXTENSIONS:
            max_size = self.MAX_IMAGE_SIZE
            file_type = "image"
        else:  # Video
            max_size = self.MAX_VIDEO_SIZE
            file_type = "video"
        
        # Check file size
        if file.size > max_size:
            max_size_mb = max_size / (1024 * 1024)
            raise ValidationError(
                f"File size exceeds maximum allowed size of {max_size_mb}MB for {file_type}s. "
                f"Your file is {file.size / (1024 * 1024):.2f}MB."
            )
        
        return file
    
    def get_file_type(self):
        """Determine file type from uploaded file"""
        if not self.is_valid():
            return None
        
        file = self.cleaned_data.get('evidence_file')
        if not file:
            return None
        
        ext = os.path.splitext(file.name)[1].lower()
        if ext in self.ALLOWED_IMAGE_EXTENSIONS:
            return 'IMAGE'
        elif ext in self.ALLOWED_VIDEO_EXTENSIONS:
            return 'VIDEO'
        return None