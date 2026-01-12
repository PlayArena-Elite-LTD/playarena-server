from django import forms
from .models import Match

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