from django.db import models
from django.conf import settings

# Get the user model from settings
User = settings.AUTH_USER_MODEL

class Message(models.Model):
    sender = models.ForeignKey(User, related_name='sent_messages', on_delete=models.CASCADE)
    receiver = models.ForeignKey(User, related_name='received_messages', on_delete=models.CASCADE)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"From {self.sender} to {self.receiver}: {self.message[:30]}"

class ReadMessage(models.Model):
    message = models.ForeignKey(Message, related_name='read_marks', on_delete=models.CASCADE)
    receiver = models.ForeignKey(User, related_name='read_messages', on_delete=models.CASCADE)
    read_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['message', 'receiver']  # A message can only be read once by a user

    def __str__(self):
        return f"Read by {self.receiver} at {self.read_at}: {self.message.message[:30]}"