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
from django.http import HttpResponse, JsonResponse

from .models import Profile
from .forms import PreSignupForm, CustomUserCreationForm, UserForm, ProfileForm
from .login_form import EmailOrUsernameAuthenticationForm

User = get_user_model()


@ratelimit(key='ip', rate='3/h', method='POST', block=True)
def pre_signup(request):
    # Show maintenance page instead of pre-signup
    return render(request, 'maintenance.html')

def pre_signup_done(request):
    return render(request, 'registration/pre_signup_done.html')


@ratelimit(key='ip', rate='3/h', method='POST', block=True)
def signup(request):
    # Show maintenance page instead of signup
    return render(request, 'maintenance.html')

class CustomLoginView(LoginView):
    authentication_form = EmailOrUsernameAuthenticationForm
    template_name = 'maintenance.html'
    
    @ratelimit(key='ip', rate='5/15m', method='POST', block=True)
    def post(self, request, *args, **kwargs):
        """Apply rate limiting to login POST requests"""
        return render(request, 'maintenance.html')
    
    def dispatch(self, request, *args, **kwargs):
        # Show maintenance page instead of login
        return render(request, 'maintenance.html')
    
def logout_view(request):
    """
    Enhanced logout view that completely clears the session.
    This ensures admins are fully logged out and cannot access user accounts.
    """
    # Store message before logout (since logout clears session)
    from django.contrib import messages
    messages.success(request, 'You have been logged out successfully.')
    
    # Logout the user (this also flushes the session internally)
    logout(request)
    
    # Create a response to ensure cookies are cleared
    response = redirect('login')
    
    # Explicitly delete session cookie to ensure it's removed from browser
    # This prevents any session persistence after logout
    # Get session cookie name from settings (default is 'sessionid')
    from django.conf import settings
    session_cookie_name = getattr(settings, 'SESSION_COOKIE_NAME', 'sessionid')
    response.delete_cookie(
        session_cookie_name,
        path=settings.SESSION_COOKIE_PATH if hasattr(settings, 'SESSION_COOKIE_PATH') else '/',
        domain=settings.SESSION_COOKIE_DOMAIN if hasattr(settings, 'SESSION_COOKIE_DOMAIN') else None
    )
    
    return response
    
@login_required
def dashboard(request):
    return render(request, 'dashboard.html')
    
@login_required
def settings_view(request):
    return render(request, 'profiles/settings.html')

# Custom password reset view with rate limiting
from django.contrib.auth.views import PasswordResetView as BasePasswordResetView

def get_email_from_form(request):
    """Extract email from password reset form for rate limiting"""
    if request.method == 'POST' and 'email' in request.POST:
        email = request.POST['email']
        # Rate limit by email to prevent abuse of specific email addresses
        return f"email:{email}"
    # Fallback to IP if no email provided
    return f"ip:{request.META.get('REMOTE_ADDR', 'unknown')}"

class RateLimitedPasswordResetView(BasePasswordResetView):
    """Password reset view with rate limiting"""
    html_email_template_name = 'registration/password_reset_email.html'
    email_template_name = 'registration/password_reset_email.html'
    
    @ratelimit(key=get_email_from_form, rate='3/h', method='POST', block=True)
    def post(self, request, *args, **kwargs):
        """Apply rate limiting based on email"""
        return super().post(request, *args, **kwargs)


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