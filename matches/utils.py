"""
Utility functions for evidence file validation and processing.
"""
from django.conf import settings
from django.core.exceptions import ValidationError
import os
import hashlib


def validate_evidence_file(file, file_type):
    """
    Validate evidence file type and size.
    
    Security: Comprehensive validation of file type (MIME type and extension) and size.
    
    Args:
        file: Django UploadedFile instance
        file_type: 'IMAGE' or 'VIDEO'
    
    Returns:
        dict: {
            'valid': bool,
            'errors': list of error messages
        }
    
    Raises:
        ValidationError: If validation fails
    """
    errors = []
    
    if not file:
        raise ValidationError("File is required")
    
    # Get file size
    file_size = file.size
    
    # Validate file size based on type
    if file_type == 'IMAGE':
        if file_size > settings.MAX_IMAGE_SIZE:
            max_mb = settings.MAX_IMAGE_SIZE / (1024 * 1024)
            errors.append(
                f'Image file size exceeds maximum allowed size of {max_mb}MB. '
                f'Your file is {file_size / (1024 * 1024):.2f}MB.'
            )
    elif file_type == 'VIDEO':
        if file_size > settings.MAX_VIDEO_SIZE:
            max_mb = settings.MAX_VIDEO_SIZE / (1024 * 1024)
            errors.append(
                f'Video file size exceeds maximum allowed size of {max_mb}MB. '
                f'Your file is {file_size / (1024 * 1024):.2f}MB.'
            )
    else:
        errors.append(f'Invalid file type: {file_type}')
    
    # Validate MIME type
    content_type = file.content_type
    if file_type == 'IMAGE':
        if content_type not in settings.ALLOWED_IMAGE_TYPES:
            errors.append(
                f'Invalid image file type. Allowed types: {", ".join(settings.ALLOWED_IMAGE_TYPES)}'
            )
    elif file_type == 'VIDEO':
        if content_type not in settings.ALLOWED_VIDEO_TYPES:
            errors.append(
                f'Invalid video file type. Allowed types: {", ".join(settings.ALLOWED_VIDEO_TYPES)}'
            )
    
    # Validate file extension
    file_name = file.name.lower()
    if file_type == 'IMAGE':
        if not any(file_name.endswith(ext) for ext in settings.ALLOWED_IMAGE_EXTENSIONS):
            errors.append(
                f'Invalid image file extension. Allowed extensions: {", ".join(settings.ALLOWED_IMAGE_EXTENSIONS)}'
            )
    elif file_type == 'VIDEO':
        if not any(file_name.endswith(ext) for ext in settings.ALLOWED_VIDEO_EXTENSIONS):
            errors.append(
                f'Invalid video file extension. Allowed extensions: {", ".join(settings.ALLOWED_VIDEO_EXTENSIONS)}'
            )
    
    if errors:
        raise ValidationError(errors)
    
    return {'valid': True, 'errors': []}


def get_file_type(file):
    """
    Detect file type from file content type and extension.
    
    Args:
        file: Django UploadedFile instance
    
    Returns:
        str: 'IMAGE' or 'VIDEO' or None if cannot determine
    """
    if not file:
        return None
    
    content_type = file.content_type
    file_name = file.name.lower()
    
    # Check if it's an image
    if content_type in settings.ALLOWED_IMAGE_TYPES:
        if any(file_name.endswith(ext) for ext in settings.ALLOWED_IMAGE_EXTENSIONS):
            return 'IMAGE'
    
    # Check if it's a video
    if content_type in settings.ALLOWED_VIDEO_TYPES:
        if any(file_name.endswith(ext) for ext in settings.ALLOWED_VIDEO_EXTENSIONS):
            return 'VIDEO'
    
    return None


def get_file_size_mb(file):
    """
    Get file size in megabytes (human-readable).
    
    Args:
        file: Django UploadedFile instance
    
    Returns:
        float: File size in MB
    """
    if not file:
        return 0
    
    file_size = file.size
    return round(file_size / (1024 * 1024), 2)


def is_valid_image(file):
    """
    Check if file is a valid image.
    
    Args:
        file: Django UploadedFile instance
    
    Returns:
        bool: True if file is a valid image
    """
    if not file:
        return False
    
    content_type = file.content_type
    file_name = file.name.lower()
    
    return (content_type in settings.ALLOWED_IMAGE_TYPES and
            any(file_name.endswith(ext) for ext in settings.ALLOWED_IMAGE_EXTENSIONS))


def is_valid_video(file):
    """
    Check if file is a valid video.
    
    Args:
        file: Django UploadedFile instance
    
    Returns:
        bool: True if file is a valid video
    """
    if not file:
        return False
    
    content_type = file.content_type
    file_name = file.name.lower()
    
    return (content_type in settings.ALLOWED_VIDEO_TYPES and
            any(file_name.endswith(ext) for ext in settings.ALLOWED_VIDEO_EXTENSIONS))


def validate_file_size(file, file_type):
    """
    Validate file size based on file type.
    
    Args:
        file: Django UploadedFile instance
        file_type: 'IMAGE' or 'VIDEO'
    
    Raises:
        ValidationError: If file size exceeds limits
    """
    if not file:
        raise ValidationError("File is required")
    
    file_size = file.size
    
    if file_type == 'IMAGE':
        if file_size > settings.MAX_IMAGE_SIZE:
            max_mb = settings.MAX_IMAGE_SIZE / (1024 * 1024)
            raise ValidationError(
                f'Image file size exceeds maximum allowed size of {max_mb}MB. '
                f'Your file is {file_size / (1024 * 1024):.2f}MB.'
            )
    elif file_type == 'VIDEO':
        if file_size > settings.MAX_VIDEO_SIZE:
            max_mb = settings.MAX_VIDEO_SIZE / (1024 * 1024)
            raise ValidationError(
                f'Video file size exceeds maximum allowed size of {max_mb}MB. '
                f'Your file is {file_size / (1024 * 1024):.2f}MB.'
            )
    else:
        raise ValidationError(f'Invalid file type: {file_type}')


def validate_file_type(file, file_type):
    """
    Validate file MIME type and extension.
    
    Args:
        file: Django UploadedFile instance
        file_type: 'IMAGE' or 'VIDEO'
    
    Raises:
        ValidationError: If file type is invalid
    """
    if not file:
        raise ValidationError("File is required")
    
    content_type = file.content_type
    file_name = file.name.lower()
    
    if file_type == 'IMAGE':
        if content_type not in settings.ALLOWED_IMAGE_TYPES:
            raise ValidationError(
                f'Invalid image file type. Allowed types: {", ".join(settings.ALLOWED_IMAGE_TYPES)}'
            )
        if not any(file_name.endswith(ext) for ext in settings.ALLOWED_IMAGE_EXTENSIONS):
            raise ValidationError(
                f'Invalid image file extension. Allowed extensions: {", ".join(settings.ALLOWED_IMAGE_EXTENSIONS)}'
            )
    elif file_type == 'VIDEO':
        if content_type not in settings.ALLOWED_VIDEO_TYPES:
            raise ValidationError(
                f'Invalid video file type. Allowed types: {", ".join(settings.ALLOWED_VIDEO_TYPES)}'
            )
        if not any(file_name.endswith(ext) for ext in settings.ALLOWED_VIDEO_EXTENSIONS):
            raise ValidationError(
                f'Invalid video file extension. Allowed extensions: {", ".join(settings.ALLOWED_VIDEO_EXTENSIONS)}'
            )
    else:
        raise ValidationError(f'Invalid file type: {file_type}')


def generate_file_hash(file):
    """
    Generate SHA256 hash of file content for integrity checking.
    
    Security: Creates a hash to detect file tampering.
    
    Args:
        file: Django UploadedFile or file-like object
    
    Returns:
        str: SHA256 hash in hexadecimal format, or None if file is invalid
    """
    if not file:
        return None
    
    try:
        # Handle Django UploadedFile
        if hasattr(file, 'read'):
            # Save current position
            current_position = file.tell() if hasattr(file, 'tell') else 0
            # Reset to beginning
            file.seek(0)
            # Read file content
            file_content = file.read()
            # Restore position
            if hasattr(file, 'seek'):
                file.seek(current_position)
        # Handle file path
        elif isinstance(file, str) and os.path.exists(file):
            with open(file, 'rb') as f:
                file_content = f.read()
        else:
            return None
        
        # Generate SHA256 hash
        file_hash = hashlib.sha256(file_content).hexdigest()
        return file_hash
    except Exception:
        return None
