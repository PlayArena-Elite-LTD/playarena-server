from django.db import models
from django.conf import settings

class Notification(models.Model):
    """Model to store user notifications"""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications')
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Notification for {self.user.username}: {self.message[:30]}..."
    
    @property
    def is_read(self):
        """Check if the notification has been read"""
        return ReadNotification.objects.filter(notification=self, user=self.user).exists()


class ReadNotification(models.Model):
    """Model to track read status of notifications"""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    notification = models.ForeignKey(Notification, on_delete=models.CASCADE)
    read_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['user', 'notification']
        
    def __str__(self):
        return f"{self.user.username} read notification at {self.read_at}"