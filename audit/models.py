from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()


class AuditLog(models.Model):
    """
    Audit log model to track user actions and system events.
    Records critical operations for security, compliance, and debugging.
    """
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_logs',
        help_text='User who performed the action (null for system actions)'
    )
    action = models.CharField(
        max_length=100,
        db_index=True,
        help_text='Action performed (e.g., "deposit_created", "match_joined", "dispute_resolved")'
    )
    timestamp = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        help_text='When the action occurred'
    )
    details = models.TextField(
        blank=True,
        help_text='Additional details about the action (JSON or text)'
    )
    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        help_text='IP address of the user who performed the action'
    )
    user_agent = models.CharField(
        max_length=500,
        blank=True,
        help_text='User agent string from the request'
    )

    class Meta:
        verbose_name = 'Audit Log'
        verbose_name_plural = 'Audit Logs'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['-timestamp', 'action']),
            models.Index(fields=['user', '-timestamp']),
            models.Index(fields=['action', '-timestamp']),
        ]

    def __str__(self):
        user_str = self.user.username if self.user else 'System'
        return f"{user_str} - {self.action} - {self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}"
