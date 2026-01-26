from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone
import random
import string
import os

class Match(models.Model):
    # Game choices
    GAME_CHOICES = [
        ('FIFA_MOBILE', 'FIFA 25'),
        ('DREAM_LEAGUE_SOCCER', 'Dream League Soccer'),
        ('LI_CHESS', 'Li Chess'),
        ('CHESS.COM', 'Chess.com'),
    ]
    
    # Device choices
    DEVICE_CHOICES = [
        ('MOBILE', 'Mobile'),
    ]
    
    # Privacy choices
    PRIVACY_CHOICES = [
        ('PRIVATE', 'Private (only players with code can join)'),
        ('PUBLIC', 'Public (any player can join)'),
    ]
    
    # Amount choices
    AMOUNT_CHOICES = [
        (5, '$5'),
        (10, '$10'),
        (15, '$15'),
        (20, '$20'),
        (30, '$30'),
        (50, '$50'),
        (80, '$80'),
        (100, '$100'),
        (150, '$150'),
        (200, '$200'),
        (250, '$250'),
        (300, '$300'),
        (350, '$350'),
        (400, '$400'),
        (450, '$450'),
        (500, '$500'),
    ]
    
    # Fields
    creator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='created_matches')
    joiner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='joined_matches', null=True, blank=True)
    game = models.CharField(max_length=20, choices=GAME_CHOICES)
    device = models.CharField(max_length=10, choices=DEVICE_CHOICES)
    privacy = models.CharField(max_length=10, choices=PRIVACY_CHOICES)
    joining_code = models.CharField(max_length=10, unique=True, editable=False)
    amount = models.IntegerField(choices=AMOUNT_CHOICES)
    winnings = models.IntegerField(editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, default='OPEN', choices=[
        ('OPEN', 'Open'),
        ('JOINED', 'Joined'),
        ('COMPLETED', 'Completed'),
        ('DISPUTED', 'Disputed'),
    ])
    winner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='won_matches'
    ) 
    
    def save(self, *args, **kwargs):
    		# Generate a random joining code if one doesn't exist
    		if not self.joining_code:
        		self.joining_code = self._generate_unique_code()

    		# Set winnings to 90% of amount * 2
    		self.winnings = int(self.amount * 2 * 0.9)

    		super().save(*args, **kwargs)
    
    def _generate_unique_code(self):
        # Generate a random 10-character alphanumeric code
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))
        
        # Check if code is unique, regenerate if not
        if Match.objects.filter(joining_code=code).exists():
            return self._generate_unique_code()
        return code
    
    def __str__(self):
        return f"{self.get_game_display()} match for ${self.amount} ({self.joining_code})"
        
        
class MatchResult(models.Model):
    # Submission choices
    SUBMISSION_CHOICES = [
        ('WON', 'Won'),
        ('LOST', 'Lost'),
        ('DRAW', 'Draw'),
    ]
    
    match = models.OneToOneField(Match, on_delete=models.CASCADE, related_name='result')
    creator_submission = models.CharField(max_length=4, choices=SUBMISSION_CHOICES, null=True, blank=True)
    creator_submission_time = models.DateTimeField(null=True, blank=True)
    joiner_submission = models.CharField(max_length=4, choices=SUBMISSION_CHOICES, null=True, blank=True)
    joiner_submission_time = models.DateTimeField(null=True, blank=True)
    submission_round = models.IntegerField(default=1)
    
    def __str__(self):
        return f"Result for {self.match}"


def evidence_upload_path(instance, filename):
    """Generate upload path for evidence files"""
    # Organize files by match ID and user ID
    match_id = instance.match.id
    user_id = instance.user.id
    # Get file extension
    ext = filename.split('.')[-1]
    # Create unique filename with timestamp
    timestamp = timezone.now().strftime('%Y%m%d_%H%M%S')
    return f'evidence/match_{match_id}/user_{user_id}/{timestamp}.{ext}'


class Evidence(models.Model):
    """Model for storing evidence files (screenshots/videos) for matches"""
    
    FILE_TYPE_CHOICES = [
        ('IMAGE', 'Image'),
        ('VIDEO', 'Video'),
    ]
    
    # File size limits (in bytes)
    MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10MB
    MAX_VIDEO_SIZE = 50 * 1024 * 1024  # 50MB
    
    # Allowed file extensions
    ALLOWED_IMAGE_EXTENSIONS = ['.jpg', '.jpeg', '.png']
    ALLOWED_VIDEO_EXTENSIONS = ['.mp4', '.mov']
    
    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name='evidence')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='uploaded_evidence')
    file = models.FileField(upload_to=evidence_upload_path, help_text='Evidence file (image or video)')
    file_type = models.CharField(max_length=10, choices=FILE_TYPE_CHOICES, help_text='Type of evidence file')
    description = models.TextField(blank=True, null=True, help_text='Optional description of the evidence')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-uploaded_at']
        verbose_name = 'Evidence'
        verbose_name_plural = 'Evidence'
        indexes = [
            models.Index(fields=['match', 'user']),
            models.Index(fields=['uploaded_at']),
        ]
    
    def clean(self):
        """Validate file size and type"""
        if self.file:
            # Get file extension
            file_name = self.file.name
            ext = os.path.splitext(file_name)[1].lower()
            
            # Determine file type based on extension
            if ext in self.ALLOWED_IMAGE_EXTENSIONS:
                detected_type = 'IMAGE'
                max_size = self.MAX_IMAGE_SIZE
                allowed_exts = self.ALLOWED_IMAGE_EXTENSIONS
            elif ext in self.ALLOWED_VIDEO_EXTENSIONS:
                detected_type = 'VIDEO'
                max_size = self.MAX_VIDEO_SIZE
                allowed_exts = self.ALLOWED_VIDEO_EXTENSIONS
            else:
                raise ValidationError({
                    'file': f'Unsupported file type. Allowed types: Images ({", ".join(self.ALLOWED_IMAGE_EXTENSIONS)}), Videos ({", ".join(self.ALLOWED_VIDEO_EXTENSIONS)})'
                })
            
            # Set file_type if not already set
            if not self.file_type:
                self.file_type = detected_type
            
            # Validate file type matches extension
            if self.file_type != detected_type:
                raise ValidationError({
                    'file_type': f'File type mismatch. File extension suggests {detected_type.lower()}, but file_type is set to {self.file_type.lower()}.'
                })
            
            # Check file size
            if hasattr(self.file, 'size'):
                file_size = self.file.size
                if file_size > max_size:
                    max_size_mb = max_size / (1024 * 1024)
                    raise ValidationError({
                        'file': f'File size exceeds maximum allowed size of {max_size_mb}MB for {detected_type.lower()}s.'
                    })
    
    def save(self, *args, **kwargs):
        """Override save to run validation"""
        self.full_clean()
        super().save(*args, **kwargs)
    
    def get_file_size_display(self):
        """Return human-readable file size"""
        if self.file and hasattr(self.file, 'size'):
            size = self.file.size
            for unit in ['B', 'KB', 'MB', 'GB']:
                if size < 1024.0:
                    return f"{size:.2f} {unit}"
                size /= 1024.0
            return f"{size:.2f} TB"
        return "Unknown"
    
    def __str__(self):
        return f"Evidence for {self.match} by {self.user.username} ({self.get_file_type_display()})"