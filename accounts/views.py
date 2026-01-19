from django import forms
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, get_user_model
from django.contrib.auth.decorators import login_required
from datetime import datetime
from django.contrib.auth.views import LoginView
from django.contrib.auth.forms import AuthenticationForm
from django.core import signing
from django.core.mail import send_mail, EmailMultiAlternatives
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse, reverse_lazy
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django_ratelimit.decorators import ratelimit

from .models import Profile
from .forms import PreSignupForm, CustomUserCreationForm, UserForm, ProfileForm
from .login_form import EmailOrUsernameAuthenticationForm

User = get_user_model()

@ratelimit(key='ip', rate='3/h', block=True)
def pre_signup(request):
    if request.method == 'POST':
        form = PreSignupForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            
            # Check if email already exists before sending link
            if User.objects.filter(email=email).exists():
                messages.error(request, f"An account with email {email} already exists.")
                return render(request, 'registration/pre_signup.html', {'form': form})
            
            # Create token
            token = signing.dumps(email) 
            signup_url = request.build_absolute_uri(reverse('signup') + f'?token={token}')
            
            # Improved email content with HTML
            subject = 'Your Manduna Registration Link'
            html_content = render_to_string('emails/signup_email.html', {
                'signup_url': signup_url,
                'expiry_hours': 24,
            })
            text_content = strip_tags(html_content)
            
            # Send email with error handling
            try:
                email_msg = EmailMultiAlternatives(
                    subject, 
                    text_content, 
                    'admin@playarena.com', 
                    [email]
                )
                email_msg.attach_alternative(html_content, "text/html")
                email_msg.send()
                return redirect('pre_signup_done')
            except Exception as e:
                messages.error(request, "Failed to send verification email. Please try again.")
                return render(request, 'registration/pre_signup.html', {'form': form})
    else:
        form = PreSignupForm()
    return render(request, 'registration/pre_signup.html', {'form': form})

def pre_signup_done(request):
    return render(request, 'registration/pre_signup_done.html')

@ratelimit(key='ip', rate='3/h', block=True)
def signup(request):
    initial = {}
    if 'token' in request.GET:
        token = request.GET['token']
        try:
            email = signing.loads(token, max_age=86400)  # 24 hours
            initial['email'] = email
            
            # Check if email already exists before form processing
            if User.objects.filter(email=email).exists():
                return render(request, 'registration/pre_signup_email_exists.html', {'email': email})
                
        except signing.BadSignature:
            return render(request, 'registration/pre_signup_email_error.html')
        except signing.SignatureExpired:
            return render(request, 'registration/pre_signup_email_expired.html')
    else:
        return redirect('pre_signup')
        
    form = CustomUserCreationForm(request.POST or None, initial=initial)
    if form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, 'Account created successfully, welcome!')
        return redirect('profile_edit')
    return render(request, 'registration/signup.html', {'form': form})

class CustomLoginView(LoginView):
    authentication_form = EmailOrUsernameAuthenticationForm
    template_name = 'registration/login.html'
    
    @ratelimit(key='ip', rate='5/m', block=True)
    def dispatch(self, request, *args, **kwargs):
        # Check if user is already authenticated
        if request.user.is_authenticated:
            # Redirect to dashboard
            return redirect('dashboard')  # Use your dashboard URL name here
        
        # Otherwise, proceed with normal login flow
        return super().dispatch(request, *args, **kwargs)
    
def logout_view(request):
    logout(request)
    messages.success(request, 'You have been logged out successfully.')
    return redirect('login')
    
@login_required
def dashboard(request):
    return render(request, 'dashboard.html')
    
@login_required
def settings_view(request):
    return render(request, 'profiles/settings.html')

@login_required
def profile_view(request):
    """View for displaying the user's profile."""
    # Try to get the profile, create if it doesn't exist
    try:
        profile = request.user.profile
    except Profile.DoesNotExist:
        profile = Profile.objects.create(user=request.user)
    return render(request, 'profiles/profile.html', {'profile': profile})

@login_required
def profile_edit(request):
    """View for editing the user's profile."""
    user = request.user
    try:
        profile = user.profile
    except Profile.DoesNotExist:
        profile = Profile.objects.create(user=user)
    
    if request.method == 'POST':
        user_form = UserForm(request.POST, instance=user)
        profile_form = ProfileForm(request.POST, instance=profile)
        
        if user_form.is_valid() and profile_form.is_valid():
            user_form.save()
            profile_form.save()
            messages.success(request, 'Your profile was successfully updated!')
            return redirect('profile')
    else:
        user_form = UserForm(instance=user)
        profile_form = ProfileForm(instance=profile)
    
    # Combine forms for template
    forms = [user_form, profile_form]
    return render(request, 'profiles/profile_edit.html', {'forms': forms})