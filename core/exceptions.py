"""
Custom exceptions for rate limiting
"""
from django.http import HttpResponse
import json


class RateLimitExceeded(Exception):
    """Custom exception for rate limit exceeded"""
    def __init__(self, message="Rate limit exceeded", retry_after=None):
        self.message = message
        self.retry_after = retry_after
        super().__init__(self.message)


def rate_limit_handler(request, exception):
    """
    Custom handler for rate limit exceptions
    Returns user-friendly error messages with HTTP 429 status
    """
    import logging
    logger = logging.getLogger('django_ratelimit')
    
    # Log the rate limit violation
    ip_address = request.META.get('REMOTE_ADDR', 'Unknown')
    path = request.path
    logger.warning(f"Rate limit exceeded for IP {ip_address} on path {path}")
    
    # Determine error message based on endpoint
    if 'login' in path:
        message = "Too many login attempts. Please wait 15 minutes before trying again."
    elif 'signup' in path or 'pre-signup' in path:
        message = "Too many registration attempts. Please wait 1 hour before trying again."
    elif 'password_reset' in path:
        message = "Too many password reset requests. Please wait 1 hour before trying again."
    elif 'deposit' in path:
        message = "Too many deposit requests. Please wait 1 minute before trying again."
    elif 'withdraw' in path:
        message = "Too many withdrawal requests. Please wait 1 hour before trying again."
    elif 'balance' in path or 'wallet' in path:
        message = "Too many balance check requests. Please wait 1 minute before trying again."
    elif 'create' in path and 'match' in path:
        message = "Too many match creation requests. Please wait 1 hour before trying again."
    elif 'result' in path or 'submit' in path:
        message = "Too many result submission requests. Please wait 1 hour before trying again."
    else:
        message = "Too many requests. Please wait a moment before trying again."
    
    response_data = {
        'error': 'Rate limit exceeded',
        'message': message,
        'status_code': 429
    }
    
    # If request is AJAX/JSON, return JSON response
    if request.headers.get('Content-Type', '').startswith('application/json') or \
       request.headers.get('Accept', '').startswith('application/json'):
        response = HttpResponse(
            json.dumps(response_data),
            content_type='application/json',
            status=429
        )
    else:
        # For regular HTTP requests, return HTML response
        from django.contrib import messages
        from django.shortcuts import redirect
        messages.error(request, message)
        # Try to redirect to referer or login
        redirect_url = request.META.get('HTTP_REFERER', '/login/')
        return redirect(redirect_url)
    
    # Set Retry-After header if provided
    if hasattr(exception, 'retry_after') and exception.retry_after:
        response['Retry-After'] = str(exception.retry_after)
    else:
        response['Retry-After'] = '900'  # Default 15 minutes in seconds
    
    return response











