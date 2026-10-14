from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from decimal import Decimal, ROUND_HALF_UP
import random
import string
import hashlib

from accounts.models import Organisation


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


def _default_platform_fee_percent():
    """Default PlayArena administration percentage (from settings)."""
    return Decimal(str(getattr(settings, 'TOURNAMENT_PLATFORM_FEE_PERCENT', 10)))


class Tournament(models.Model):
    STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('OPEN', 'Registration Open'),
        ('REG_CLOSED', 'Registration Closed'),
        ('SCHEDULED', 'Scheduled'),
        ('READY_TO_START', 'Ready to Start'),
        ('LIVE', 'Live'),
        ('RESULTS_PENDING', 'Results Pending'),
        ('COMPLETED', 'Completed'),
        ('PAYOUT_PROCESSING', 'Payout Processing'),
        ('PAID', 'Paid / Settled'),
        ('CANCELLED', 'Cancelled'),
    ]

    # Statuses before play begins — registration edits / withdrawals allowed.
    PRE_PLAY_STATUSES = ('DRAFT', 'OPEN', 'REG_CLOSED', 'SCHEDULED', 'READY_TO_START')
    # Terminal statuses — no further lifecycle changes.
    TERMINAL_STATUSES = ('COMPLETED', 'PAYOUT_PROCESSING', 'PAID', 'CANCELLED')

    organisation = models.ForeignKey(
        Organisation,
        on_delete=models.CASCADE,
        related_name='tournaments',
    )
    FORMAT_CHOICES = [
        ('KNOCKOUT', 'Knockout / Cup'),
        ('LEAGUE', '7-Day League'),
    ]

    name = models.CharField(max_length=255)
    game = models.CharField(max_length=32, choices=Match.GAME_CHOICES)
    format = models.CharField(max_length=20, choices=FORMAT_CHOICES, default='KNOCKOUT')
    platform_fee_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=_default_platform_fee_percent,
        validators=[MinValueValidator(0), MaxValueValidator(10)],
        help_text="PlayArena administration fee percentage (organiser-configurable from 0% to 10%).",
    )
    home_and_away = models.BooleanField(
        default=True,
        help_text="Leagues only: play each matchup twice (home and away). Knockouts are always single-leg.",
    )
    participation_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
    )
    max_players = models.PositiveIntegerField(validators=[MinValueValidator(2)])
    rules = models.TextField(blank=True)
    start_date = models.DateField(null=True, blank=True)
    registration_opens_at = models.DateTimeField(null=True, blank=True)
    registration_closes_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='OPEN')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.organisation.name})"

    @staticmethod
    def default_fee_percent():
        """Default PlayArena administration percentage (from settings)."""
        return _default_platform_fee_percent()

    def fee_percent(self):
        """Configured PlayArena administration fee for this tournament."""
        return self.platform_fee_percent

    def split_entry(self, amount):
        """Split an entry fee into (platform_fee, prize_contribution).

        PlayArena keeps ``fee_percent()``% of the entry as the administration
        fee; the remainder is the player's contribution to the prize pool. The
        fee is rounded to 2 dp and the contribution is the exact remainder, so
        the two always sum back to the original entry with no rounding drift.
        """
        amount = Decimal(amount)
        fee = (amount * self.fee_percent() / Decimal('100')).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )
        contribution = amount - fee
        return fee, contribution

    def _registration_sum(self, field):
        total = self.registrations.filter(
            status=TournamentRegistration.Status.REGISTERED
        ).aggregate(total=models.Sum(field))['total']
        return total or Decimal('0.00')

    @property
    def registered_players_count(self):
        """Number of players actively registered for this tournament."""
        return self.registrations.filter(
            status=TournamentRegistration.Status.REGISTERED
        ).count()

    @property
    def gross_entries(self):
        """Total entry fees collected from active registrations."""
        return self._registration_sum('amount_paid')

    @property
    def platform_fee_total(self):
        """Platform fee reserved or recognized at full-capacity confirmation."""
        settlement = getattr(self, 'fee_settlement', None)
        if settlement:
            if settlement.status in (
                TournamentFeeSettlement.Status.RESERVED,
                TournamentFeeSettlement.Status.RECOGNIZED,
            ):
                return settlement.platform_fee
            return Decimal('0.00')
        return self._registration_sum('platform_fee')

    @property
    def prize_pool(self):
        """Net distributable pool after full-capacity fee confirmation."""
        settlement = getattr(self, 'fee_settlement', None)
        if settlement:
            if settlement.status in (
                TournamentFeeSettlement.Status.RESERVED,
                TournamentFeeSettlement.Status.RECOGNIZED,
            ):
                return settlement.net_prize_pool
            return Decimal('0.00')
        return self._registration_sum('prize_contribution')

    @property
    def is_full(self):
        return self.registered_players_count >= self.max_players

    @property
    def past_registration_deadline(self):
        return bool(self.registration_closes_at and timezone.now() >= self.registration_closes_at)

    @property
    def registration_not_yet_open(self):
        return bool(self.registration_opens_at and timezone.now() < self.registration_opens_at)

    @property
    def is_registration_open(self):
        """Whether a player can currently register."""
        return (
            self.status == 'OPEN'
            and not self.registration_not_yet_open
            and not self.past_registration_deadline
            and not self.is_full
        )

    @property
    def display_status(self):
        """Status for display: reflects auto-close on deadline/capacity even if
        the stored status hasn't been persisted yet."""
        if self.status == 'OPEN' and (self.is_full or self.past_registration_deadline):
            return 'REG_CLOSED'
        return self.status

    def auto_close_registration(self):
        """Persist REG_CLOSED when an OPEN tournament hits capacity or deadline."""
        if self.status == 'OPEN' and (self.is_full or self.past_registration_deadline):
            self.status = 'REG_CLOSED'
            self.save(update_fields=['status'])
            return True
        return False


class TournamentFeeSettlement(models.Model):
    """One-time gross/admin-fee/net snapshot for a full organisation tournament.

    RESERVED is created atomically when every slot is filled. The fee is
    recognized only when the tournament actually starts. A pre-launch
    cancellation or participant withdrawal invalidates the reservation.
    """

    class Status(models.TextChoices):
        RESERVED = 'RESERVED', 'Reserved'
        RECOGNIZED = 'RECOGNIZED', 'Recognized'
        VOID = 'VOID', 'Voided'
        REFUNDED = 'REFUNDED', 'Refunded'

    tournament = models.OneToOneField(
        Tournament,
        on_delete=models.PROTECT,
        related_name='fee_settlement',
    )
    gross_pool = models.DecimalField(max_digits=16, decimal_places=2)
    platform_fee = models.DecimalField(max_digits=16, decimal_places=2)
    net_prize_pool = models.DecimalField(max_digits=16, decimal_places=2)
    fee_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('10.00'))
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.RESERVED,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    recognized_at = models.DateTimeField(null=True, blank=True)
    reversed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return (
            f"Tournament fee #{self.tournament_id}: {self.platform_fee} "
            f"({self.get_status_display()})"
        )


class TournamentRegistration(models.Model):
    """A player's participation in a tournament.

    Mirrors the 1-on-1 match join flow: joining debits the player's wallet by the
    participation amount and creates a registration; leaving (while the tournament
    is still OPEN) refunds the stake and marks the registration WITHDRAWN.
    """

    class Status(models.TextChoices):
        REGISTERED = 'REGISTERED', 'Registered'
        WITHDRAWN = 'WITHDRAWN', 'Withdrawn'

    tournament = models.ForeignKey(
        Tournament,
        on_delete=models.CASCADE,
        related_name='registrations',
    )
    player = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='tournament_registrations',
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.REGISTERED,
    )
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2)
    platform_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="PlayArena administration fee allocated from this entry.",
    )
    prize_contribution = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Portion of this entry added to the tournament prize pool.",
    )
    team_name = models.CharField(
        max_length=120,
        blank=True,
        default='',
        help_text="Team the player represents in this tournament (e.g. 'Power Dynamos').",
    )
    phone = models.CharField(
        max_length=32,
        blank=True,
        default='',
        help_text="WhatsApp / phone number for the player, stored with the +260 country code where applicable.",
    )
    joined_at = models.DateTimeField(auto_now_add=True)
    left_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-joined_at']
        constraints = [
            models.UniqueConstraint(
                fields=['tournament', 'player'],
                name='unique_tournament_player_registration',
            ),
        ]

    def __str__(self):
        return f"{self.player} -> {self.tournament.name} ({self.status})"


class TournamentPrize(models.Model):
    """A configurable payout position for a tournament.

    Admins/organisers configure the prize split as a percentage of the prize
    pool per finishing position (1st, 2nd, ...). Percentages across a
    tournament's positions must not exceed 100%. The actual cash value is
    derived from the live prize pool so players can see expected winnings
    before registering.
    """

    tournament = models.ForeignKey(
        Tournament,
        on_delete=models.CASCADE,
        related_name='prizes',
    )
    position = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
        help_text="Finishing position: 1 = 1st place, 2 = 2nd place, ...",
    )
    percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Share of the prize pool awarded to this position.",
    )

    class Meta:
        ordering = ['position']
        constraints = [
            models.UniqueConstraint(
                fields=['tournament', 'position'],
                name='unique_tournament_prize_position',
            ),
        ]

    def __str__(self):
        return f"{self.tournament.name} #{self.position}: {self.percentage}%"

    def expected_amount(self, prize_pool=None):
        """Cash value of this position given a prize pool (defaults to live pool)."""
        if prize_pool is None:
            prize_pool = self.tournament.prize_pool
        return (Decimal(prize_pool) * self.percentage / Decimal('100')).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )


class TournamentStanding(models.Model):
    """A player's final (or draft) position in a tournament.

    Format-agnostic: whatever the game or format, a tournament resolves to a set
    of ranked positions. Organisers enter/edit these, then lock them; locking
    freezes the standings and triggers automatic payouts from the prize pool.
    """

    tournament = models.ForeignKey(
        Tournament,
        on_delete=models.CASCADE,
        related_name='standings',
    )
    player = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='tournament_standings',
    )
    position = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
        help_text="Final rank: 1 = winner, 2 = runner-up, ...",
    )
    points = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Optional score/points for display (game-specific).",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['position']
        constraints = [
            models.UniqueConstraint(
                fields=['tournament', 'player'],
                name='unique_tournament_standing_player',
            ),
            models.UniqueConstraint(
                fields=['tournament', 'position'],
                name='unique_tournament_standing_position',
            ),
        ]

    def __str__(self):
        return f"{self.tournament.name} #{self.position}: {self.player}"


class TournamentPayout(models.Model):
    """An automatic payout to a winning position after final results are locked.

    Records remain traceable even when crediting fails, so winnings are never
    lost and a failed payout can be resolved/retried by an organiser.
    """

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        PAID = 'PAID', 'Paid'
        FAILED = 'FAILED', 'Failed'

    tournament = models.ForeignKey(
        Tournament,
        on_delete=models.CASCADE,
        related_name='payouts',
    )
    player = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='tournament_payouts',
    )
    position = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    transaction = models.ForeignKey(
        'wallet.Transaction',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='tournament_payouts',
    )
    failure_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['position']
        constraints = [
            models.UniqueConstraint(
                fields=['tournament', 'position'],
                name='unique_tournament_payout_position',
            ),
        ]

    def __str__(self):
        return f"{self.tournament.name} #{self.position}: {self.amount} ({self.status})"


class TournamentMatch(models.Model):
    """A single-elimination bracket match within a tournament.

    Matches are laid out by round (1 = first round) and slot (order within the
    round). Each non-final match points to the ``next_match`` its winner
    advances into, filling ``next_slot`` (1 or 2). Byes auto-advance.
    """

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'        # slot(s) still to be filled (TBD)
        READY = 'READY', 'Ready'              # both players known, awaiting result
        REPORTED = 'REPORTED', 'Reported'     # one player submitted, awaiting the other
        DISPUTED = 'DISPUTED', 'Disputed'     # both submitted but disagree — organiser resolves
        CONFIRMED = 'CONFIRMED', 'Confirmed'  # result final
        BYE = 'BYE', 'Bye'                    # auto-advanced (no opponent)

    tournament = models.ForeignKey(
        Tournament,
        on_delete=models.CASCADE,
        related_name='bracket_matches',
    )
    round_number = models.PositiveIntegerField()
    slot_number = models.PositiveIntegerField()
    player1 = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    player2 = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    winner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    player1_score = models.PositiveSmallIntegerField(null=True, blank=True)
    player2_score = models.PositiveSmallIntegerField(null=True, blank=True)
    reported_winner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    reported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    next_match = models.ForeignKey(
        'self', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    next_slot = models.PositiveSmallIntegerField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['round_number', 'slot_number']
        constraints = [
            models.UniqueConstraint(
                fields=['tournament', 'round_number', 'slot_number'],
                name='unique_tournament_match_slot',
            ),
        ]

    def __str__(self):
        return f"{self.tournament.name} R{self.round_number}.{self.slot_number} ({self.status})"

    def has_player(self, user_id):
        return user_id in (self.player1_id, self.player2_id)


def tournament_evidence_path(instance, filename):
    return f"tournament_evidence/{instance.match.tournament_id}/{instance.match_id}/{filename}"


class TournamentMatchSubmission(models.Model):
    """One participant's submitted result for a tournament match.

    Mirrors the 1v1 flow: both players submit; if they agree the match
    auto-confirms, if they disagree the match is Disputed for the organiser to
    resolve. Knockout submissions carry a ``winner``; league submissions carry
    a scoreline. An optional screenshot can back the claim.
    """

    match = models.ForeignKey(
        TournamentMatch,
        on_delete=models.CASCADE,
        related_name='submissions',
    )
    player = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+',
    )
    # Knockout: who this player says won.
    winner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    # League: the scoreline this player reports (player1 vs player2 orientation).
    player1_score = models.PositiveSmallIntegerField(null=True, blank=True)
    player2_score = models.PositiveSmallIntegerField(null=True, blank=True)
    evidence = models.FileField(upload_to=tournament_evidence_path, null=True, blank=True)
    submitted_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['submitted_at']
        constraints = [
            models.UniqueConstraint(
                fields=['match', 'player'],
                name='unique_tournament_match_submission',
            ),
        ]

    def __str__(self):
        return f"{self.player} → {self.match} submission"
