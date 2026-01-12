from django.db import models
from django.conf import settings
import random
import string

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