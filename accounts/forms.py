from django import forms
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from django.contrib.auth import get_user_model
from .models import CustomUser, Profile

SIGNUP_EMAIL_TAKEN_MSG = 'This email is already registered. Please login instead.'
SIGNUP_USERNAME_TAKEN_MSG = 'This username is already taken. Please choose another.'


def signup_integrity_error_messages(exc):
    """Map unique-constraint IntegrityErrors to field messages (concurrent signup races)."""
    message = str(exc).lower()
    errors = {}
    if 'email' in message:
        errors['email'] = SIGNUP_EMAIL_TAKEN_MSG
    if 'username' in message:
        errors['username'] = SIGNUP_USERNAME_TAKEN_MSG
    return errors


def apply_signup_integrity_errors_to_form(form, exc):
    field_errors = signup_integrity_error_messages(exc)
    for field, msg in field_errors.items():
        form.add_error(field, msg)
    return bool(field_errors)


class CustomUserCreationForm(UserCreationForm):
    #email = forms.EmailField(required=True, widget=forms.HiddenInput(), help_text='')

    class Meta:
        model = CustomUser
        fields = ("username", "email")

    def __init__(self, *args, signup_email=None, **kwargs):
        self.signup_email = signup_email
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

    def clean(self):
        cleaned_data = super().clean()
        email = self.signup_email or cleaned_data.get('email')
        username = cleaned_data.get('username')

        if email and CustomUser.objects.filter(email=email).exists():
            self.add_error('email', SIGNUP_EMAIL_TAKEN_MSG)

        if username and CustomUser.objects.filter(username=username).exists():
            self.add_error('username', SIGNUP_USERNAME_TAKEN_MSG)

        return cleaned_data

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

    def clean_email(self):
        email = self.cleaned_data['email']
        if CustomUser.objects.filter(email=email).exists():
            raise forms.ValidationError(SIGNUP_EMAIL_TAKEN_MSG)
        return email
    
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