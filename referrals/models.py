"""Referral program data models.

Implements the four tables from the PlayArena Referral Program spec plus an
isolated referral wallet (spec section 8). The commission ledger is the
immutable source of truth: balances are only ever changed alongside a ledger
row (see ``referrals.services``).
"""
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models


def default_commission_rate():
    """Platform default referral commission rate (percent of platform fee)."""
    return Decimal(str(getattr(settings, "REFERRAL_DEFAULT_COMMISSION_RATE", 30)))


class Referrer(models.Model):
    """A user approved to earn referral commission (spec section 4)."""

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        SUSPENDED = "SUSPENDED", "Suspended"
        REJECTED = "REJECTED", "Rejected"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="referrer",
    )
    referral_code = models.CharField(max_length=50, unique=True, db_index=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    commission_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=default_commission_rate,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Configurable per-referrer commission rate (percent of platform fee).",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.referral_code} ({self.get_status_display()})"

    @property
    def is_active(self):
        return self.status == self.Status.APPROVED

    def effective_rate(self):
        """Per-referrer override, falling back to the platform default."""
        if self.commission_rate is not None:
            return Decimal(self.commission_rate)
        return default_commission_rate()

    def share_url(self):
        base = getattr(settings, "REFERRAL_SHARE_BASE_URL", "").rstrip("/")
        if base:
            return f"{base}/register?ref={self.referral_code}"
        return f"/register?ref={self.referral_code}"


class Referral(models.Model):
    """Permanent referrer -> player relationship (spec sections 3 and 4).

    ``referred_user`` is unique, enforcing the "first valid referral wins /
    permanent" attribution rule: a player can only ever be referred once.
    """

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        INACTIVE = "INACTIVE", "Inactive"

    referrer = models.ForeignKey(
        Referrer, on_delete=models.CASCADE, related_name="referrals"
    )
    referred_user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="referred_by",
    )
    referral_code = models.CharField(
        max_length=50, help_text="Code used at registration (audit trail)."
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.ACTIVE
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.referrer.referral_code} -> {self.referred_user}"


class ReferralCommissionLedger(models.Model):
    """Immutable per-transaction commission record (spec sections 4 and 5).

    Every balance change on a referral wallet is backed by a row here. A
    reversal (spec section 6) is recorded as a NEW row with a negative amount and
    ``reversal_of`` pointing at the original; the original is never deleted.
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        AVAILABLE = "AVAILABLE", "Available"
        PAID = "PAID", "Paid"
        REVERSED = "REVERSED", "Reversed"
        CANCELLED = "CANCELLED", "Cancelled"

    referrer = models.ForeignKey(
        Referrer, on_delete=models.PROTECT, related_name="ledger_entries"
    )
    referred_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="generated_commissions",
    )
    transaction = models.OneToOneField(
        "wallet.Transaction",
        on_delete=models.PROTECT,
        related_name="referral_commission",
        null=True,
        blank=True,
        help_text="Source stake/entry transaction that generated the platform fee.",
    )
    related_match = models.ForeignKey(
        "matches.Match", on_delete=models.SET_NULL, null=True, blank=True
    )
    related_tournament = models.ForeignKey(
        "matches.Tournament", on_delete=models.SET_NULL, null=True, blank=True
    )
    platform_fee = models.DecimalField(
        max_digits=12, decimal_places=2, help_text="Platform fee this entry is based on."
    )
    commission_rate = models.DecimalField(max_digits=5, decimal_places=2)
    commission_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Earned commission (negative for reversal entries).",
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    reversal_of = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reversed_by",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["referrer", "status"]),
            models.Index(fields=["referred_user"]),
        ]

    def __str__(self):
        return (
            f"Ledger #{self.pk} {self.referrer.referral_code} "
            f"{self.commission_amount} ({self.get_status_display()})"
        )


class ReferralWallet(models.Model):
    """Isolated commission balance, separate from the gaming wallet (spec 8)."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="referral_wallet",
    )
    balance = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"ReferralWallet({self.user}) = {self.balance}"

    def _ledger_sum(self, status):
        if not hasattr(self.user, "referrer"):
            return Decimal("0.00")
        agg = self.user.referrer.ledger_entries.filter(status=status).aggregate(
            total=models.Sum("commission_amount")
        )
        return agg["total"] or Decimal("0.00")

    def outstanding_withdrawals(self):
        """Sum of withdrawals that have reserved funds (not rejected)."""
        if not hasattr(self.user, "referrer"):
            return Decimal("0.00")
        agg = self.user.referrer.withdrawals.exclude(
            status=ReferralWithdrawal.Status.REJECTED
        ).aggregate(total=models.Sum("amount"))
        return agg["total"] or Decimal("0.00")

    @property
    def available_balance(self):
        """Balance eligible for withdrawal: cleared commission minus any
        withdrawals already requested/approved/paid (so funds can't be
        withdrawn twice)."""
        cleared = self._ledger_sum(ReferralCommissionLedger.Status.AVAILABLE)
        return cleared - self.outstanding_withdrawals()

    @property
    def pending_balance(self):
        return self._ledger_sum(ReferralCommissionLedger.Status.PENDING)

    def verify_balance_integrity(self):
        """Balance must equal PENDING + AVAILABLE ledger rows (mirrors wallet.Wallet)."""
        expected = self.pending_balance + self.available_balance
        discrepancy = self.balance - expected
        return {
            "is_valid": discrepancy == Decimal("0.00"),
            "expected_balance": expected,
            "actual_balance": self.balance,
            "discrepancy": discrepancy,
        }


class ReferralWithdrawal(models.Model):
    """Payout request against the referral wallet (spec sections 4 and 8)."""

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        PAID = "PAID", "Paid"

    referrer = models.ForeignKey(
        Referrer, on_delete=models.PROTECT, related_name="withdrawals"
    )
    amount = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))]
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    payment_reference = models.CharField(max_length=100, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Withdrawal #{self.pk} {self.amount} ({self.get_status_display()})"
