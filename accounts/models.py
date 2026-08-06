from django.contrib.auth.models import AbstractUser
from django.db import models
from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

class CustomUser(AbstractUser):
    # AbstractUser already includes username field as unique
    # Override email field to make it unique
    email = models.EmailField(unique=True)
    is_support_staff = models.BooleanField(default=False)

    def __str__(self):
        return self.username
        

class Profile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile')
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    
    def __str__(self):
        return f"{self.user.username}'s Profile"


class Organisation(models.Model):
    class OrganisationType(models.TextChoices):
        TOURNAMENT_ORGANISER = 'TOURNAMENT_ORGANISER', 'Tournament organiser'
        GAMING_LOUNGE = 'GAMING_LOUNGE', 'Gaming lounge'
        ESPORTS_TEAM = 'ESPORTS_TEAM', 'Esports team'
        SCHOOL_UNIVERSITY = 'SCHOOL_UNIVERSITY', 'School or university'
        BRAND_SPONSOR = 'BRAND_SPONSOR', 'Brand or sponsor'
        COMMUNITY_GROUP = 'COMMUNITY_GROUP', 'Community group'

    owner = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='organisation',
    )
    name = models.CharField(max_length=255)
    contact_name = models.CharField(max_length=150)
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=32)
    organisation_type = models.CharField(
        max_length=32,
        choices=OrganisationType.choices,
        default=OrganisationType.TOURNAMENT_ORGANISER,
    )
    city = models.CharField(max_length=120)
    is_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name


class OrganisationMembership(models.Model):
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        APPROVED = 'APPROVED', 'Approved'
        REJECTED = 'REJECTED', 'Rejected'

    organisation = models.ForeignKey(
        Organisation,
        on_delete=models.CASCADE,
        related_name='memberships',
    )
    player = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='organisation_memberships',
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    requested_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_organisation_memberships',
    )

    class Meta:
        ordering = ['-requested_at']
        constraints = [
            models.UniqueConstraint(
                fields=['organisation', 'player'],
                name='unique_organisation_player_membership',
            ),
        ]

    def __str__(self):
        return f"{self.player} -> {self.organisation} ({self.status})"

@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(user=instance)

@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def save_user_profile(sender, instance, **kwargs):
    instance.profile.save()
