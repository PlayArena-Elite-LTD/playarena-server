"""
Security utility functions for input sanitization and validation.

This module provides helper functions for sanitizing user inputs
to prevent XSS attacks and other security vulnerabilities.
"""

from django.utils.html import escape
from django.utils.text import slugify
import re
from html import unescape


def sanitize_html(text):
    """
    Sanitize HTML input by escaping special characters.
    
    Args:
        text: Input string that may contain HTML
        
    Returns:
        Escaped string safe for HTML output
    """
    if text is None:
        return ''
    return escape(str(text))


def sanitize_for_display(text, max_length=None):
    """
    Sanitize text for safe display in templates.
    Strips HTML tags and escapes special characters.
    
    Args:
        text: Input string
        max_length: Optional maximum length to truncate
        
    Returns:
        Sanitized string safe for display
    """
    if text is None:
        return ''
    
    text = str(text)
    
    # Remove any HTML tags (basic sanitization)
    text = re.sub(r'<[^>]+>', '', text)
    
    # Escape HTML entities
    text = escape(text)
    
    # Truncate if max_length specified
    if max_length and len(text) > max_length:
        text = text[:max_length] + '...'
    
    return text


def sanitize_username(username):
    """
    Sanitize and validate username input.
    Only allows alphanumeric characters, underscores, and hyphens.
    
    Args:
        username: Username string
        
    Returns:
        Sanitized username or None if invalid
    """
    if not username:
        return None
    
    username = username.strip()
    
    # Only allow alphanumeric, underscore, and hyphen
    if re.match(r'^[a-zA-Z0-9_-]+$', username):
        return username
    
    return None


def sanitize_email(email):
    """
    Basic email sanitization (trim whitespace, lowercase).
    Note: Django forms provide more comprehensive email validation.
    
    Args:
        email: Email string
        
    Returns:
        Sanitized email or None if invalid
    """
    if not email:
        return None
    
    email = email.strip().lower()
    
    # Basic email format check
    if re.match(r'^[^@]+@[^@]+\.[^@]+$', email):
        return email
    
    return None


def sanitize_numeric_input(value, min_value=None, max_value=None):
    """
    Sanitize numeric input and validate range.
    
    Args:
        value: Numeric value (string or number)
        min_value: Optional minimum value
        max_value: Optional maximum value
        
    Returns:
        Validated number or None if invalid
    """
    try:
        num = float(value)
        
        if min_value is not None and num < min_value:
            return None
        if max_value is not None and num > max_value:
            return None
            
        return num
    except (ValueError, TypeError):
        return None


def sanitize_url(url):
    """
    Basic URL sanitization and validation.
    
    Args:
        url: URL string
        
    Returns:
        Sanitized URL or None if invalid
    """
    if not url:
        return None
    
    url = url.strip()
    
    # Basic URL format check
    url_pattern = re.compile(
        r'^https?://'  # http:// or https://
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'  # domain...
        r'localhost|'  # localhost...
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # ...or ip
        r'(?::\d+)?'  # optional port
        r'(?:/?|[/?]\S+)$', re.IGNORECASE)
    
    if url_pattern.match(url):
        return url
    
    return None
