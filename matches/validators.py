"""
Django form validators for evidence file validation.
These validators can be reused across forms and models.
"""
from django.core.exceptions import ValidationError
from django.conf import settings
from .utils import validate_file_size, validate_file_type, is_valid_image, is_valid_video


def validate_evidence_image(file):
    """
    Django validator for image evidence files.
    
    Usage:
        from matches.validators import validate_evidence_image
        file = forms.FileField(validators=[validate_evidence_image])
    
    Args:
        file: Django UploadedFile instance
    
    Raises:
        ValidationError: If file is not a valid image
    """
    if not file:
        raise ValidationError("File is required")
    
    if not is_valid_image(file):
        raise ValidationError(
            f'Invalid image file. Allowed types: {", ".join(settings.ALLOWED_IMAGE_TYPES)}. '
            f'Allowed extensions: {", ".join(settings.ALLOWED_IMAGE_EXTENSIONS)}'
        )
    
    # Validate file size
    try:
        validate_file_size(file, 'IMAGE')
    except ValidationError as e:
        raise ValidationError(str(e))


def validate_evidence_video(file):
    """
    Django validator for video evidence files.
    
    Usage:
        from matches.validators import validate_evidence_video
        file = forms.FileField(validators=[validate_evidence_video])
    
    Args:
        file: Django UploadedFile instance
    
    Raises:
        ValidationError: If file is not a valid video
    """
    if not file:
        raise ValidationError("File is required")
    
    if not is_valid_video(file):
        raise ValidationError(
            f'Invalid video file. Allowed types: {", ".join(settings.ALLOWED_VIDEO_TYPES)}. '
            f'Allowed extensions: {", ".join(settings.ALLOWED_VIDEO_EXTENSIONS)}'
        )
    
    # Validate file size
    try:
        validate_file_size(file, 'VIDEO')
    except ValidationError as e:
        raise ValidationError(str(e))


def validate_evidence_file_size(file, max_size_bytes):
    """
    Generic validator for file size.
    
    Usage:
        from matches.validators import validate_evidence_file_size
        file = forms.FileField(validators=[lambda f: validate_evidence_file_size(f, 10*1024*1024)])
    
    Args:
        file: Django UploadedFile instance
        max_size_bytes: Maximum file size in bytes
    
    Raises:
        ValidationError: If file exceeds maximum size
    """
    if not file:
        raise ValidationError("File is required")
    
    if file.size > max_size_bytes:
        max_mb = max_size_bytes / (1024 * 1024)
        file_mb = file.size / (1024 * 1024)
        raise ValidationError(
            f'File size exceeds maximum allowed size of {max_mb}MB. '
            f'Your file is {file_mb:.2f}MB.'
        )
