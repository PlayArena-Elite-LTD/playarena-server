"""
Utility functions for audit logging.

This module provides helper functions to create audit log entries
for tracking user actions and system events.
"""
import logging
import json
from typing import Optional, Dict, Any
from django.contrib.auth import get_user_model
from django.http import HttpRequest

from .models import AuditLog

User = get_user_model()
logger = logging.getLogger('audit')


def get_client_ip(request: HttpRequest) -> Optional[str]:
    """
    Extract client IP address from request.
    
    Handles various proxy headers (X-Forwarded-For, X-Real-IP, etc.)
    to get the actual client IP address.
    
    Args:
        request: Django HttpRequest object
        
    Returns:
        IP address string or None if not found
    """
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        # X-Forwarded-For can contain multiple IPs, take the first one
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def get_user_agent(request: HttpRequest) -> str:
    """
    Extract user agent string from request.
    
    Args:
        request: Django HttpRequest object
        
    Returns:
        User agent string or empty string if not found
    """
    return request.META.get('HTTP_USER_AGENT', '')


def log_action(
    action: str,
    user: Optional[User] = None,
    details: Optional[Dict[str, Any]] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    request: Optional[HttpRequest] = None,
) -> Optional[AuditLog]:
    """
    Create an audit log entry for a user action or system event.
    
    This function provides a convenient way to log actions across the application.
    It handles errors gracefully to ensure audit logging failures don't break
    the main application flow.
    
    Args:
        action: Action identifier (e.g., 'deposit_created', 'match_joined', 'dispute_resolved')
        user: User who performed the action (None for system actions)
        details: Dictionary with additional details about the action (will be JSON-encoded)
        ip_address: IP address of the user (will be extracted from request if not provided)
        user_agent: User agent string (will be extracted from request if not provided)
        request: Django HttpRequest object (used to extract IP and user agent if not provided)
        
    Returns:
        AuditLog instance if successful, None if creation failed
        
    Example:
        # Log a deposit creation
        log_action(
            action='deposit_created',
            user=request.user,
            details={'deposit_id': deposit.id, 'amount': str(deposit.amount)},
            request=request
        )
        
        # Log a system action
        log_action(
            action='wallet_reconciliation',
            details={'wallets_checked': 100, 'discrepancies': 0}
        )
    """
    try:
        # Extract IP and user agent from request if not provided
        if request:
            if ip_address is None:
                ip_address = get_client_ip(request)
            if user_agent is None:
                user_agent = get_user_agent(request)
        
        # Convert details dict to JSON string if provided
        details_str = ''
        if details:
            try:
                details_str = json.dumps(details, default=str)
            except (TypeError, ValueError) as e:
                logger.warning(f"Failed to serialize audit log details: {e}")
                details_str = str(details)
        
        # Create audit log entry
        audit_log = AuditLog.objects.create(
            action=action,
            user=user,
            details=details_str,
            ip_address=ip_address,
            user_agent=user_agent or '',
        )
        
        logger.debug(f"Audit log created: {action} by {user.username if user else 'System'}")
        return audit_log
        
    except Exception as e:
        # Log the error but don't raise it - audit logging should never break the main flow
        logger.error(
            f"Failed to create audit log entry for action '{action}': {e}",
            exc_info=True
        )
        return None
