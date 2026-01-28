from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone
import random
import string
import hashlib
import os
from .utils import validate_file_size, validate_file_type

class Match(models.Model):
    # Game choices
    GAME_CHOICES = [
        ('FIFA_MOBILE', 'FIFA 25'),
        ('DREAM_LEAGUE_SOCCER', 'Dream League Soccer'),
        ('LI_CHESS', 'Li Chess'),
        ('CHESS.COM', 'Chess.com'),
        ('NBA_2K', 'NBA 2K'),
        ('MORTAL_KOMBAT', 'Mortal Kombat'),
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
    device = models.CharField(max_length=15, choices=DEVICE_CHOICES)
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
    """
    Model to track match result submissions from both players.
    
    Evidence is linked through the Match model via Evidence model (ForeignKey to Match).
    Access evidence via: match.evidence.all() or use the evidence property below.
    """
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
    
    @property
    def evidence(self):
        """
        Get all evidence for this match result.
        
        Returns queryset of Evidence objects linked to the match.
        Evidence is stored via Evidence model (ForeignKey to Match), not directly on MatchResult.
        This allows multiple evidence files per match.
        """
        return self.match.evidence.all()
    
    @property
    def creator_evidence(self):
        """Get evidence submitted by the match creator"""
        return self.match.evidence.filter(user=self.match.creator)
    
    @property
    def joiner_evidence(self):
        """Get evidence submitted by the match joiner"""
        if self.match.joiner:
            return self.match.evidence.filter(user=self.match.joiner)
        return self.match.evidence.none()
    
    @property
    def has_evidence(self):
        """Check if any evidence has been submitted for this match"""
        return self.match.evidence.exists()


class Evidence(models.Model):
    """
    Model to store evidence files (screenshots/videos) for match results.
    
    Security features:
    - File type validation (images/videos only)
    - File size limits (10MB images, 50MB videos)
    - File hash for integrity checking
    - IP address and user agent tracking
    - Organized file storage by date
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
    file_size = models.PositiveIntegerField(help_text='File size in bytes')
    file_hash = models.CharField(max_length=64, blank=True, null=True, help_text='SHA256 hash for integrity checking')
    ip_address = models.GenericIPAddressField(blank=True, null=True, help_text='IP address of upload request')
    user_agent = models.CharField(max_length=500, blank=True, null=True, help_text='User agent of upload request')

    # Internal support staff notes (not visible to regular users)
    staff_notes = models.TextField(
        blank=True,
        null=True,
        help_text='Internal notes/comments added by support staff during dispute review'
    )
    
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
        indexes = [
            models.Index(fields=['match', 'user']),
            models.Index(fields=['uploaded_at']),
            models.Index(fields=['file_type']),
            models.Index(fields=['is_verified']),
        ]
        verbose_name = 'Evidence'
        verbose_name_plural = 'Evidence'
    
    def __str__(self):
        return f"Evidence for {self.match} by {self.user.username} ({self.get_file_type_display()})"
    
    def clean(self):
        """Security: Validate file type and size using utility functions"""
        if not self.file:
            return  # File validation happens in form/view
        
        # Only validate if file is an UploadedFile (during upload), not FieldFile (after save)
        # FieldFile objects don't have content_type attribute
        if not hasattr(self.file, 'content_type'):
            return  # File already saved, validation was done during upload
        
        # Get file size
        if hasattr(self.file, 'size'):
            file_size = self.file.size
        elif hasattr(self.file, 'file'):
            file_size = self.file.file.size
        else:
            raise ValidationError({'file': 'Unable to determine file size'})
        
        # Validate file size using utility function
        try:
            validate_file_size(self.file, self.file_type)
        except ValidationError as e:
            raise ValidationError({'file': str(e)})
        
        # Validate file type using utility function
        try:
            validate_file_type(self.file, self.file_type)
        except ValidationError as e:
            raise ValidationError({'file': str(e)})
        
        # Validate file size field matches actual file
        if self.file_size and self.file_size != file_size:
            raise ValidationError({
                'file_size': 'File size does not match actual file size'
            })
    
    def save(self, *args, **kwargs):
        """Security: Generate file hash and validate before saving"""
        # Generate file hash if file exists and hash not set
        if self.file and not self.file_hash:
            self.file_hash = self.generate_file_hash()
        
        # Set file size if not set
        if self.file and not self.file_size:
            if hasattr(self.file, 'size'):
                self.file_size = self.file.size
            elif hasattr(self.file, 'file'):
                self.file_size = self.file.file.size
        
        # Run validation
        self.full_clean()
        
        super().save(*args, **kwargs)
    
    def generate_file_hash(self):
        """
        Generate SHA256 hash of file content for integrity checking.
        
        Security: Creates a hash to detect file tampering.
        """
        if not self.file:
            return None
        
        try:
            # Read file content
            if hasattr(self.file, 'read'):
                self.file.seek(0)
                file_content = self.file.read()
            elif hasattr(self.file, 'file'):
                self.file.file.seek(0)
                file_content = self.file.file.read()
            else:
                return None
            
            # Generate hash
            file_hash = hashlib.sha256(file_content).hexdigest()
            
            # Reset file pointer
            if hasattr(self.file, 'seek'):
                self.file.seek(0)
            elif hasattr(self.file, 'file'):
                self.file.file.seek(0)
            
            return file_hash
        except Exception:
            return None
    
    def verify_hash(self):
        """
        Verify that the current file content matches the stored hash.
        
        Security: Detects if file has been tampered with.
        """
        if not self.file_hash:
            return False
        
        current_hash = self.generate_file_hash()
        return current_hash == self.file_hash
    
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
    
    def mark_as_verified(self, verified_by_user):
        """
        Mark evidence as verified by support staff.
        
        Security: Only support staff can verify evidence.
        """
        if not verified_by_user.is_support_staff:
            raise ValidationError('Only support staff can verify evidence')
        
        self.is_verified = True
        self.verified_by = verified_by_user
        self.verified_at = timezone.now()
        self.save(update_fields=['is_verified', 'verified_by', 'verified_at'])