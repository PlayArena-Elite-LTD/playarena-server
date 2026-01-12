from django import forms
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from django.contrib.auth import get_user_model
from .models import CustomUser, Profile

class CustomUserCreationForm(UserCreationForm):
    #email = forms.EmailField(required=True, widget=forms.HiddenInput(), help_text='')

    class Meta:
        model = CustomUser
        fields = ("username", "email")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Remove help text from all fields
        for fieldname in self.fields:
            self.fields[fieldname].help_text = ''

        # If email is provided in initial data, make it read-only with css class
        if 'initial' in kwargs and 'email' in kwargs['initial']:
            self.fields['email'].disabled = True
            self.fields['email'].widget.attrs.update({
                'class': 'disabled-email',
            })

class CustomUserChangeForm(UserChangeForm):
    class Meta:
        model = CustomUser
        fields = ('username', 'email')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Remove help text from all fields
        for fieldname in self.fields:
            self.fields[fieldname].help_text = ''

class PreSignupForm(forms.Form):
    email = forms.EmailField(help_text='')
    
User = get_user_model()

class UserForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['username', 'email']
        labels = {
            'username': 'Username',
            'email': 'Email',
        }
        
class ProfileForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ['first_name', 'last_name']
        labels = {
            'first_name': 'First Name',
            'last_name': 'Last Name',
        }
        
class UserProfileForm:
    """
    A class that combines both UserForm and ProfileForm
    """
    def __init__(self, *args, **kwargs):
        self.user_form = UserForm(*args, **kwargs)
        self.profile_form = ProfileForm(*args, **kwargs)
        
    def is_valid(self):
        return self.user_form.is_valid() and self.profile_form.is_valid()
    
    def save(self):
        self.user_form.save()
        self.profile_form.save()