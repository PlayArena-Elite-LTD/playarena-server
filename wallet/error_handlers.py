"""
Security-focused error handling and logging utilities for payment operations

Security priorities:
- Never expose internal errors to users
- Sanitize all logs (no sensitive data)
- Track security-relevant events
- Classify errors (security vs operational)
- Implement fraud detection triggers
"""

import logging
import traceback
from functools import wraps
from datetime import timedelta
from django.http import JsonResponse, HttpResponse
from django.shortcuts import redirect
from django.contrib import messages
from django.db import DatabaseError, IntegrityError
from django.utils import timezone
from decimal import Decimal, InvalidOperation

from .models import Deposit

logger = logging.getLogger(__name__)
security_logger = logging.getLogger('security')  # Separate logger for security events


class PaymentError(Exception):
    """Base exception for payment-related errors"""
    def __init__(self, message, user_message=None, security_risk=False):
        self.message = message
        self.user_message = user_message or "An error occurred. Please try again or contact support."
        self.security_risk = security_risk
        super().__init__(self.message)


class PaymentSecurityError(PaymentError):
    """Security-related payment errors (fraud, tampering, etc.)"""
    def __init__(self, message, user_message=None):
        super().__init__(message, user_message, security_risk=True)


class PaymentGatewayError(PaymentError):
    """Payment gateway API errors"""
    pass


class PaymentValidationError(PaymentError):
    """Payment validation errors"""
    pass


def sanitize_error_message(error, context=None):
    """
    Sanitize error messages to prevent sensitive data exposure
    
    Security: Removes API keys, tokens, passwords, and other sensitive info
    """
    error_str = str(error)
    
    # Remove potential sensitive patterns
    sensitive_patterns = [
        r'sk_live_[a-zA-Z0-9]+',
        r'sk_test_[a-zA-Z0-9]+',
        r'pk_live_[a-zA-Z0-9]+',
        r'pk_test_[a-zA-Z0-9]+',
        r'FLWSECK_[a-zA-Z0-9]+',
        r'FLWPUBK_[a-zA-Z0-9]+',
        r'Bearer [a-zA-Z0-9]+',
        r'password[=:]\s*[^\s]+',
        r'api[_-]?key[=:]\s*[^\s]+',
    ]
    
    import re
    sanitized = error_str
    for pattern in sensitive_patterns:
        sanitized = re.sub(pattern, '[REDACTED]', sanitized, flags=re.IGNORECASE)
    
    return sanitized


def log_security_event(event_type, details, request=None, severity='WARNING'):
    """
    Log security-relevant events with full context
    
    Security: Tracks suspicious activity, fraud attempts, etc.
    """
    context = {
        'event_type': event_type,
        'details': details,
        'severity': severity,
    }
    
    if request:
        context.update({
            'ip_address': _get_client_ip(request),
            'user_agent': request.META.get('HTTP_USER_AGENT', '')[:200],
            'user_id': request.user.id if hasattr(request, 'user') and request.user.is_authenticated else None,
            'username': request.user.username if hasattr(request, 'user') and request.user.is_authenticated else None,
            'path': request.path,
            'method': request.method,
        })
    
    if severity == 'CRITICAL':
        security_logger.critical(f"SECURITY EVENT: {event_type}", extra=context)
    elif severity == 'ERROR':
        security_logger.error(f"SECURITY EVENT: {event_type}", extra=context)
    else:
        security_logger.warning(f"SECURITY EVENT: {event_type}", extra=context)


def _get_client_ip(request):
    """Extract client IP address securely"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def handle_payment_error(error, request=None, deposit=None, operation='payment_operation'):
    """
    Centralized error handler for payment operations
    
    Security features:
    - Sanitizes error messages
    - Classifies security vs operational errors
    - Logs with full context
    - Returns safe user messages
    """
    error_type = type(error).__name__
    sanitized_error = sanitize_error_message(error)
    
    context = {
        'operation': operation,
        'error_type': error_type,
        'error_message': sanitized_error,
    }
    
    if deposit:
        context.update({
            'deposit_id': deposit.id,
            'deposit_amount': float(deposit.amount),
            'deposit_status': deposit.status,
            'user_id': deposit.user.id,
            'username': deposit.user.username,
        })
    
    if request:
        context.update({
            'ip_address': _get_client_ip(request),
            'user_agent': request.META.get('HTTP_USER_AGENT', '')[:200],
            'path': request.path,
        })
    
    # Classify error type
    if isinstance(error, PaymentSecurityError):
        # Security error - log as security event
        log_security_event(
            'payment_security_error',
            {
                'error': sanitized_error,
                'operation': operation,
                'deposit_id': deposit.id if deposit else None,
            },
            request=request,
            severity='ERROR'
        )
        logger.error(f"Payment security error in {operation}", extra=context, exc_info=True)
        return {
            'success': False,
            'user_message': error.user_message,
            'log_message': sanitized_error,
            'security_risk': True,
        }
    
    elif isinstance(error, (DatabaseError, IntegrityError)):
        # Database error - potential data integrity issue
        log_security_event(
            'payment_database_error',
            {
                'error': sanitized_error,
                'operation': operation,
            },
            request=request,
            severity='ERROR'
        )
        logger.error(f"Database error in {operation}", extra=context, exc_info=True)
        return {
            'success': False,
            'user_message': 'A database error occurred. Please contact support.',
            'log_message': sanitized_error,
            'security_risk': False,
        }
    
    elif isinstance(error, PaymentGatewayError):
        # Gateway error - log but don't expose details
        logger.error(f"Payment gateway error in {operation}", extra=context, exc_info=True)
        return {
            'success': False,
            'user_message': error.user_message,
            'log_message': sanitized_error,
            'security_risk': False,
        }
    
    elif isinstance(error, PaymentValidationError):
        # Validation error - user-facing
        logger.warning(f"Payment validation error in {operation}", extra=context)
        return {
            'success': False,
            'user_message': error.user_message,
            'log_message': sanitized_error,
            'security_risk': False,
        }
    
    else:
        # Unknown error - log fully but don't expose
        logger.error(f"Unexpected error in {operation}", extra=context, exc_info=True)
        return {
            'success': False,
            'user_message': 'An unexpected error occurred. Please try again or contact support.',
            'log_message': sanitized_error,
            'security_risk': False,
        }


def payment_error_handler(view_func):
    """
    Decorator for payment views with comprehensive error handling
    
    Security: Wraps views to catch and handle all errors securely
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        try:
            return view_func(request, *args, **kwargs)
        except PaymentSecurityError as e:
            # Security error - log and return safe response
            result = handle_payment_error(e, request=request, operation=view_func.__name__)
            
            if request.headers.get('Content-Type', '').startswith('application/json'):
                return JsonResponse({
                    'status': 'error',
                    'message': result['user_message']
                }, status=400)
            
            messages.error(request, result['user_message'])
            return redirect('wallet')
            
        except PaymentError as e:
            # Payment error - handle gracefully
            result = handle_payment_error(e, request=request, operation=view_func.__name__)
            
            if request.headers.get('Content-Type', '').startswith('application/json'):
                return JsonResponse({
                    'status': 'error',
                    'message': result['user_message']
                }, status=400)
            
            messages.error(request, result['user_message'])
            return redirect('wallet')
            
        except Exception as e:
            # Unexpected error - log fully but don't expose
            result = handle_payment_error(e, request=request, operation=view_func.__name__)
            
            if request.headers.get('Content-Type', '').startswith('application/json'):
                return JsonResponse({
                    'status': 'error',
                    'message': result['user_message']
                }, status=500)
            
            messages.error(request, result['user_message'])
            return redirect('wallet')
    
    return wrapper


def validate_payment_amount(amount, min_amount=Decimal('1.00'), max_amount=Decimal('10000.00')):
    """
    Validate payment amount with security checks
    
    Security: Prevents invalid amounts, overflow attacks, etc.
    """
    try:
        if not isinstance(amount, Decimal):
            amount = Decimal(str(amount))
        
        if amount <= 0:
            raise PaymentValidationError(
                "Amount must be positive",
                user_message="Payment amount must be greater than zero."
            )
        
        if amount < min_amount:
            raise PaymentValidationError(
                f"Amount below minimum: {min_amount}",
                user_message=f"Minimum payment amount is ${min_amount:.2f}"
            )
        
        if amount > max_amount:
            raise PaymentValidationError(
                f"Amount exceeds maximum: {max_amount}",
                user_message=f"Maximum payment amount is ${max_amount:.2f}"
            )
        
        return amount
        
    except (ValueError, InvalidOperation) as e:
        raise PaymentValidationError(
            f"Invalid amount format: {str(e)}",
            user_message="Invalid payment amount. Please enter a valid number."
        )


def detect_suspicious_activity(request, deposit=None):
    """
    Detect suspicious payment activity patterns
    
    Security: Flags potential fraud attempts
    """
    suspicious = False
    reasons = []
    
    if not request:
        return suspicious, reasons
    
    ip_address = _get_client_ip(request)
    
    # Check for rapid successive deposits from same IP
    if deposit:
        recent_deposits = Deposit.objects.filter(
            ip_address=ip_address,
            created_at__gte=timezone.now() - timedelta(minutes=5)
        ).count()
        
        if recent_deposits > 5:
            suspicious = True
            reasons.append(f"Too many deposits from same IP ({recent_deposits} in 5 minutes)")
    
    # Check for unusual user agent
    user_agent = request.META.get('HTTP_USER_AGENT', '')
    if not user_agent or len(user_agent) < 10:
        suspicious = True
        reasons.append("Missing or suspicious user agent")
    
    # Check for missing or suspicious headers
    if not request.META.get('HTTP_REFERER'):
        # Not always suspicious, but log it
        logger.debug(f"Missing referer header - IP: {ip_address}")
    
    if suspicious:
        log_security_event(
            'suspicious_payment_activity',
            {
                'reasons': reasons,
                'deposit_id': deposit.id if deposit else None,
            },
            request=request,
            severity='WARNING'
        )
    
    return suspicious, reasons
