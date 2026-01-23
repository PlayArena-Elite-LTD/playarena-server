"""
Middleware to display rate limit messages stored in session
"""
from django.contrib import messages


class RateLimitMessageMiddleware:
    """
    Middleware to display rate limit error messages from session
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Check for rate limit message in session before processing request
        if hasattr(request, 'session'):
            rate_limit_message = request.session.pop('rate_limit_message', None)
            rate_limit_message_type = request.session.pop('rate_limit_message_type', 'error')
            if rate_limit_message:
                if rate_limit_message_type == 'error':
                    messages.error(request, rate_limit_message)
                else:
                    messages.warning(request, rate_limit_message)
        
        response = self.get_response(request)
        return response











