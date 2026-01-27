"""
Signal handlers for matches app.
"""
from django.db.models.signals import post_delete, pre_delete
from django.dispatch import receiver
import os
import logging

from .models import Evidence

logger = logging.getLogger(__name__)


@receiver(post_delete, sender=Evidence)
def delete_evidence_file(sender, instance, **kwargs):
    """
    Delete the physical file when Evidence instance is deleted.
    
    Security: Prevents orphaned files from accumulating in storage.
    """
    if instance.file:
        try:
            # Delete the file from storage
            if os.path.isfile(instance.file.path):
                os.remove(instance.file.path)
                logger.info(f"Deleted evidence file: {instance.file.path}")
        except Exception as e:
            # Log error but don't fail deletion (file might already be deleted)
            logger.warning(
                f"Error deleting evidence file {instance.file.path}: {str(e)}"
            )
