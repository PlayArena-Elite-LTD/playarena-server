from django import forms
from .models import Message

class MessageForm(forms.ModelForm):
    class Meta:
        model = Message
        fields = ['message']
        widgets = {
            'message': forms.Textarea(attrs={
                'rows': 2, 
                'placeholder': 'Type your message here...',
                'class': 'message-input'
            }),
        }
        labels = {
            'message': '',  # Remove label for cleaner interface
        }