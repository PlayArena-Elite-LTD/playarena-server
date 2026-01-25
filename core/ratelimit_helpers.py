"""
Helper functions for handling rate limiting responses
"""
from django.http import HttpResponse, JsonResponse, HttpResponseRedirect
from django.contrib import messages
from django.shortcuts import redirect
import logging

logger = logging.getLogger('django_ratelimit')


def rate_limit_response(request):
    """
    Custom response function for rate limiting
    Returns user-friendly error messages with HTTP 429 status
    """
    path = request.path
    ip_address = request.META.get('REMOTE_ADDR', 'Unknown')
    user_info = f"user {request.user.username}" if hasattr(request, 'user') and request.user.is_authenticated else f"IP {ip_address}"
    
    # Determine error message based on endpoint
    if 'login' in path:
        message = "Too many login attempts. Please wait 15 minutes before trying again."
        logger.warning(f"Rate limit exceeded for login by {user_info}")
        redirect_url = '/accounts/login/'
    elif 'signup' in path or 'pre-signup' in path:
        message = "Too many registration attempts. Please wait 1 hour before trying again."
        logger.warning(f"Rate limit exceeded for registration by {user_info}")
        redirect_url = '/accounts/pre-signup/' if 'pre-signup' in path else '/accounts/signup/'
    elif 'password_reset' in path:
        message = "Too many password reset requests. Please wait 1 hour before trying again."
        logger.warning(f"Rate limit exceeded for password reset by {user_info}")
        redirect_url = '/accounts/password_reset/'
    elif 'deposit' in path:
        message = "Too many deposit requests. Please wait 1 minute before trying again."
        logger.warning(f"Rate limit exceeded for deposit by {user_info}")
        redirect_url = '/wallet/'
    elif 'withdraw' in path:
        message = "Too many withdrawal requests. Please wait 1 hour before trying again."
        logger.warning(f"Rate limit exceeded for withdrawal by {user_info}")
        redirect_url = '/wallet/'
    elif 'balance' in path:
        message = "Too many balance check requests. Please wait 1 minute before trying again."
        logger.warning(f"Rate limit exceeded for balance check by {user_info}")
        redirect_url = '/wallet/'
    elif 'create' in path and 'match' in path:
        message = "Too many match creation requests. Please wait 1 hour before trying again."
        logger.warning(f"Rate limit exceeded for match creation by {user_info}")
        redirect_url = '/matches/'
    elif 'result' in path or 'submit' in path:
        message = "Too many result submission requests. Please wait 1 hour before trying again."
        logger.warning(f"Rate limit exceeded for result submission by {user_info}")
        redirect_url = '/matches/'
    else:
        message = "Too many requests. Please wait a moment before trying again."
        logger.warning(f"Rate limit exceeded for {path} by {user_info}")
        redirect_url = '/accounts/login/' if not (hasattr(request, 'user') and request.user.is_authenticated) else '/dashboard/'
    
    # Check if request is AJAX/JSON
    is_ajax = (
        request.headers.get('Content-Type', '').startswith('application/json') or
        request.headers.get('Accept', '').startswith('application/json') or
        request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    )
    
    if is_ajax:
        response = JsonResponse({
            'error': 'Rate limit exceeded',
            'message': message,
            'status_code': 429
        }, status=429)
        response['Retry-After'] = '900'  # 15 minutes
        return response
    else:
        # Store message in session to display after redirect
        if hasattr(request, 'session'):
            request.session['rate_limit_message'] = message
            request.session['rate_limit_message_type'] = 'error'
        
        # Return redirect response with 429 status
        response = HttpResponseRedirect(redirect_url)
        response.status_code = 429
        response['Retry-After'] = '900'
        return response

