from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone
import random
import string
import hashlib

class Match(models.Model):
    # Game choices
    GAME_CHOICES = [
        ('FIFA_MOBILE', 'EA SPORTS FC 26'),
        ('DREAM_LEAGUE_SOCCER', 'Dream League Soccer 2026'),
        ('EFOOTBALL', 'eFootball 2026'),
        ('LI_CHESS', 'Lichess'),
        ('MORTAL_KOMBAT', 'Mortal Kombat 1'),
        ('NBA_2K', 'NBA 2K'),
        ('EIGHT_BALL_POOL', '8 Ball Pool'),
        ('COD_MOBILE', 'Call of Duty Mobile'),
        ('PUBG_MOBILE', 'PUBG Mobile'),
        ('CHESS_COM', 'Chess.com'),
    ]
    
    # Device choices
    DEVICE_CHOICES = [
        ('MOBILE', 'Mobile'),
        ('PLAYSTATION', 'PlayStation'),
        ('XBOX', 'Xbox'),
        ('PC', 'PC'),
    ]
    
    # Privacy choices
    PRIVACY_CHOICES = [
        ('PRIVATE', 'Private (only players with code can join)'),
        ('PUBLIC', 'Public (any player can join)'),
    ]
    
    # Amount choices
    AMOUNT_CHOICES = [
        (5, 'ZMW 5'),
        (10, 'ZMW 10'),
        (15, 'ZMW 15'),
        (20, 'ZMW 20'),
        (30, 'ZMW 30'),
        (50, 'ZMW 50'),
        (80, 'ZMW 80'),
        (100, 'ZMW 100'),
        (150, 'ZMW 150'),
        (200, 'ZMW 200'),
        (250, 'ZMW 250'),
        (300, 'ZMW 300'),
        (350, 'ZMW 350'),
        (400, 'ZMW 400'),
        (450, 'ZMW 450'),
        (500, 'ZMW 500'),
    ]
    
    # Fields
    creator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='created_matches')
    joiner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='joined_matches', null=True, blank=True)
    game = models.CharField(max_length=20, choices=GAME_CHOICES)
    # Longest value in DEVICE_CHOICES is "PLAYSTATION" (11 characters),
    # so set max_length to at least 11 to satisfy Django's system check.
    device = models.CharField(max_length=20, choices=DEVICE_CHOICES)
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
        return f"{self.get_game_display()} match for ZMW {self.amount} ({self.joining_code})"
        
        
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


class Evidence(models.Model):
    """
    Model to store evidence files (screenshots/videos) for match results.
    """
    
    FILE_TYPE_CHOICES = [
        ('IMAGE', 'Image'),
        ('VIDEO', 'Video'),
    ]
    
    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name='evidence')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='evidence_submissions')
    file = models.FileField(upload_to='evidence/%Y/%m/%d/')
    file_type = models.CharField(max_length=10, choices=FILE_TYPE_CHOICES)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    description = models.TextField(blank=True, null=True, help_text='Optional description of the evidence')
    
    # Security fields
    file_size = models.PositiveIntegerField(help_text='File size in bytes', null=True, blank=True)
    file_hash = models.CharField(max_length=64, blank=True, null=True, help_text='SHA256 hash for integrity checking')
    ip_address = models.GenericIPAddressField(blank=True, null=True, help_text='IP address of upload request')
    user_agent = models.CharField(max_length=500, blank=True, null=True, help_text='User agent of upload request')
    
    # Support staff verification
    is_verified = models.BooleanField(default=False, help_text='Verified by support staff')
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='verified_evidence',
        help_text='Support staff who verified this evidence'
    )
    verified_at = models.DateTimeField(null=True, blank=True, help_text='Timestamp when evidence was verified')
    
    class Meta:
        ordering = ['-uploaded_at']
        verbose_name = 'Evidence'
        verbose_name_plural = 'Evidence'
    
    def __str__(self):
        return f"Evidence for {self.match} by {self.user.username} ({self.get_file_type_display()})"
    
    @property
    def file_size_mb(self):
        """Return file size in megabytes (human-readable)"""
        if self.file_size:
            return round(self.file_size / (1024 * 1024), 2)
        return 0
    
    @property
    def is_image(self):
        """Check if file is an image"""
        return self.file_type == 'IMAGE'
    
    @property
    def is_video(self):
        """Check if file is a video"""
        return self.file_type == 'VIDEO'
