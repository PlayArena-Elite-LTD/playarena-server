"""
Referral program data models.

The referral system works entirely inside PlayArena.

When a referred player generates a platform fee:

    Referred player
        ↓
    Platform fee
        ↓
    Referral commission
        ↓
    ReferralCommissionLedger
        ↓
    Referrer's ReferralWallet
        ↓
    Internal transfer
        ↓
    Referrer's normal PlayArena wallet/account

IMPORTANT:
- Referral money is NOT sent directly to Airtel, MTN, Zamtel or a bank.
- There is NO external payout destination in this system.
- The commission ledger is the financial history/source of truth.
- When commission is transferred into the normal PlayArena wallet,
  the referral commission must be marked as PAID and the internal
  wallet transaction must be recorded by referrals.services.
"""

from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models


def default_commission_rate():
    """
    Get the normal commission percentage used by PlayArena.

    Example:
        Platform fee = K100
        Commission rate = 30%
        Referrer earns = K30

    If the setting is not provided, 30% is used.
    """
    return Decimal(
        str(
            getattr(
                settings,
                "REFERRAL_DEFAULT_COMMISSION_RATE",
                30,
            )
        )
    )


class Referrer(models.Model):
    """
    A PlayArena user who is allowed to earn referral commissions.
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        SUSPENDED = "SUSPENDED", "Suspended"
        REJECTED = "REJECTED", "Rejected"

    # The referrer is a normal PlayArena user.
    #
    # One user can have only ONE referrer profile.
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="referrer",
    )

    # Code that the referrer gives to other players.
    #
    # Example:
    #     JOHN123
    #
    # It must be unique so two referrers cannot have the same code.
    referral_code = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
    )

    # Controls whether this person can earn referral commission.
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )

    # Percentage of the platform fee that this referrer earns.
    #
    # Example:
    #     Platform fee = K100
    #     Rate = 30%
    #     Commission = K30
    commission_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=default_commission_rate,
        validators=[
            MinValueValidator(0),
            MaxValueValidator(100),
        ],
        help_text=(
            "Commission percentage earned from the platform fee."
        ),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.referral_code} ({self.get_status_display()})"

    @property
    def is_active(self):
        """
        A referrer can earn commission only when approved.
        """
        return self.status == self.Status.APPROVED

    def effective_rate(self):
        """
        Return the commission rate that should be used.

        If this referrer has a specific rate, use it.
        Otherwise use the platform default.
        """
        if self.commission_rate is not None:
            return Decimal(self.commission_rate)

        return default_commission_rate()

    def share_url(self):
        """
        Create the referral registration link.

        Example:
            /register?ref=JOHN123
        """
        base = getattr(
            settings,
            "REFERRAL_SHARE_BASE_URL",
            "",
        ).rstrip("/")

        if base:
            return f"{base}/register?ref={self.referral_code}"

        return f"/register?ref={self.referral_code}"


class Referral(models.Model):
    """
    Permanent relationship between:

        Referrer → Referred Player

    Once a player has been referred, another referrer cannot claim
    that same player later.

    This implements:
        "First valid referral wins."
    """

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        INACTIVE = "INACTIVE", "Inactive"

    # The person who referred the player.
    referrer = models.ForeignKey(
        Referrer,
        on_delete=models.CASCADE,
        related_name="referrals",
    )

    # The player who was referred.
    #
    # OneToOneField means a player can only have ONE referral relationship.
    referred_user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="referred_by",
    )

    # Store the actual referral code that was used during registration.
    #
    # This is useful for auditing later.
    referral_code = models.CharField(
        max_length=50,
        help_text="Referral code used during registration.",
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return (
            f"{self.referrer.referral_code} "
            f"-> {self.referred_user}"
        )


class ReferralCommissionLedger(models.Model):
    """
    Permanent financial record of referral commissions.

    Think of this as the referral system's bank statement.

    Every commission earned creates a ledger record.

    Example:

        Platform fee = K100
        Commission rate = 30%
        Commission = K30

    Ledger:

        K30 PENDING
            ↓
        K30 AVAILABLE
            ↓
        K30 PAID

    PAID means the commission has been transferred internally
    into the referrer's normal PlayArena wallet.

    IMPORTANT:
    We do NOT delete financial records.

    If a commission needs to be reversed, a NEW negative ledger
    entry is created instead of deleting the original record.
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        AVAILABLE = "AVAILABLE", "Available"

        # PAID now means:
        #
        # "This commission has already been transferred into
        #  the referrer's normal PlayArena wallet."
        PAID = "PAID", "Paid"

        REVERSED = "REVERSED", "Reversed"
        CANCELLED = "CANCELLED", "Cancelled"

    # Which referrer earned this commission?
    referrer = models.ForeignKey(
        Referrer,
        on_delete=models.PROTECT,
        related_name="ledger_entries",
    )

    # Which referred player generated the commission?
    referred_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="generated_commissions",
    )

    # The original PlayArena wallet transaction that generated
    # the platform fee.
    transaction = models.OneToOneField(
        "wallet.Transaction",
        on_delete=models.PROTECT,
        related_name="referral_commission",
        null=True,
        blank=True,
        help_text=(
            "Original wallet transaction that generated "
            "the platform fee."
        ),
    )

    # Normal-wallet debit used if an already-transferred commission is reversed.
    reversal_transaction = models.OneToOneField(
        "wallet.Transaction",
        on_delete=models.PROTECT,
        related_name="referral_commission_reversal",
        null=True,
        blank=True,
        help_text="Normal wallet debit recording a paid commission reversal.",
    )

    # Optional connection to the match that generated the fee.
    related_match = models.ForeignKey(
        "matches.Match",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    # Optional connection to the tournament that generated the fee.
    related_tournament = models.ForeignKey(
        "matches.Tournament",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    # The platform fee from which the commission was calculated.
    #
    # Example:
    #     Platform fee = K100
    platform_fee = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text=(
            "Platform fee on which the referral commission "
            "was calculated."
        ),
    )

    # Store the exact rate used at the time.
    #
    # This is important because the referrer's rate could change later.
    #
    # Example:
    #     Old rate = 30%
    #     New rate = 40%
    #
    # An old transaction must still remember that it used 30%.
    commission_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=[
            MinValueValidator(0),
            MaxValueValidator(100),
        ],
    )

    # Actual money earned by the referrer.
    #
    # Example:
    #     K100 platform fee × 30% = K30
    #
    # Normal commission:
    #     +30.00
    #
    # Reversal:
    #     -30.00
    commission_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text=(
            "Commission earned. Negative values are used "
            "for reversal entries."
        ),
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )

    # If this commission is reversed, this points to the
    # original commission entry.
    #
    # The original record is NEVER deleted.
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
            models.Index(
                fields=["referrer", "status"]
            ),
            models.Index(
                fields=["referred_user"]
            ),
        ]

    def __str__(self):
        return (
            f"Ledger #{self.pk} "
            f"{self.referrer.referral_code} "
            f"{self.commission_amount} "
            f"({self.get_status_display()})"
        )


class ReferralWallet(models.Model):
    """
    Internal referral earnings account for a referrer.

    This is NOT an Airtel/MTN/bank account.

    It is an internal PlayArena balance that keeps track of
    referral commission earned by the referrer.

    Example:

        John earns K100 referral commission.

        John's ReferralWallet:
            K0 → K100

    When the commission is transferred into John's normal
    PlayArena wallet, the referral balance is reduced and
    the normal wallet is increased.

    That actual transfer must be performed by referrals.services
    together with the normal wallet transaction/ledger.
    """

    # Every referrer gets one referral wallet.
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="referral_wallet",
    )

    # Current referral money held in this internal referral wallet.
    balance = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return (
            f"ReferralWallet({self.user}) = "
            f"{self.balance}"
        )

    def _ledger_sum(self, status):
        """
        Add together commission ledger entries with a specific status.

        Example:

            AVAILABLE:
                K20
                K30
                K50

            Total:
                K100
        """

        if not hasattr(self.user, "referrer"):
            return Decimal("0.00")

        total = (
            self.user.referrer
            .ledger_entries
            .filter(status=status)
            .aggregate(
                total=models.Sum("commission_amount")
            )
        )

        return total["total"] or Decimal("0.00")

    @property
    def available_balance(self):
        """
        Referral commission that is ready to be moved
        into the referrer's normal PlayArena wallet.

        IMPORTANT:

        We no longer subtract "withdrawals" here because
        this system is NOT an external withdrawal system.

        AVAILABLE means:
            "This commission has been earned and is ready
             for internal transfer."

        Once transferred into the normal wallet, the service
        should mark the relevant ledger entry as PAID.
        """

        return self._ledger_sum(
            ReferralCommissionLedger.Status.AVAILABLE
        )

    @property
    def pending_balance(self):
        """
        Commission that has been earned but is not yet
        available for internal transfer.
        """

        return self._ledger_sum(
            ReferralCommissionLedger.Status.PENDING
        )

    def verify_balance_integrity(self):
        """
        Check that the stored referral wallet balance agrees
        with the commission ledger.

        The referral wallet contains commission that is still
        inside the referral system:

            PENDING + AVAILABLE

        Once commission becomes PAID, it has already been
        transferred into the normal PlayArena wallet and should
        no longer be counted here.
        """

        expected = (
            self.pending_balance
            + self.available_balance
        )

        discrepancy = self.balance - expected

        return {
            "is_valid": (
                discrepancy == Decimal("0.00")
            ),
            "expected_balance": expected,
            "actual_balance": self.balance,
            "discrepancy": discrepancy,
        }


class ReferralTransfer(models.Model):
    """
    Records an INTERNAL transfer of referral commission.

    This is NOT an external withdrawal.

    The money stays inside PlayArena.

    Example:

        ReferralWallet:
            - K100

        Normal PlayArena Wallet:
            + K100

    This record exists so PlayArena can prove that the
    commission was transferred and prevent the same commission
    from being transferred twice.
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        COMPLETED = "COMPLETED", "Completed"
        FAILED = "FAILED", "Failed"

    # The referrer receiving the internal transfer.
    referrer = models.ForeignKey(
        Referrer,
        on_delete=models.PROTECT,
        related_name="commission_transfers",
    )

    # The exact commission ledger entry being transferred.
    #
    # One commission should only be transferred once.
    commission = models.OneToOneField(
        ReferralCommissionLedger,
        on_delete=models.PROTECT,
        related_name="internal_transfer",
    )

    # The credited transaction in the user's normal PlayArena wallet.
    wallet_transaction = models.OneToOneField(
        "wallet.Transaction",
        on_delete=models.PROTECT,
        related_name="referral_transfer",
    )

    # Amount being moved into the normal PlayArena wallet.
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[
            MinValueValidator(Decimal("0.01"))
        ],
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )

    # This is an INTERNAL transaction reference.
    #
    # It is not an Airtel/MTN/bank payment reference.
    #
    # Example:
    #     REF-COMMISSION-000123
    transfer_reference = models.CharField(
        max_length=100,
        blank=True,
        default=None,
        unique=True,
        null=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    completed_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return (
            f"Internal Transfer #{self.pk} "
            f"{self.referrer.referral_code} "
            f"{self.amount} "
            f"({self.get_status_display()})"
        )


class LegacyReferralWithdrawal(models.Model):
    """Read-only historical records from the retired external-payout flow.

    These rows are retained for audit purposes only. New requests and payouts
    must use ReferralTransfer and the internal PlayArena wallet.
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        PAID = "PAID", "Paid"

    referrer = models.ForeignKey(
        Referrer,
        on_delete=models.PROTECT,
        related_name="legacy_withdrawals",
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    payment_reference = models.CharField(
        max_length=100,
        blank=True,
        default="",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "referrals_referralwithdrawal"
        ordering = ["-created_at"]
        verbose_name = "legacy referral payout record"
        verbose_name_plural = "legacy referral payout records"
