"""Referral commission business logic.

Single choke point for every referral money movement so the hook sites stay
one-liners and the audit trail is guaranteed: no balance ever changes without a
corresponding immutable ledger row (spec section 5).
"""
import logging
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.db import transaction as db_tx
from django.utils import timezone

from .models import (
    Referral,
    Referrer,
    ReferralCommissionLedger,
    ReferralWallet,
)

logger = logging.getLogger(__name__)

# Platform fee is 10% of the transaction amount (matches TOURNAMENT_PLATFORM_FEE_PERCENT
# and the implicit 10% baked into 1v1 match winnings = amount * 2 * 0.9).
PLATFORM_FEE_RATE = Decimal("0.10")


def _q(amount):
    return Decimal(amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _hold_days():
    return int(getattr(settings, "REFERRAL_COMMISSION_HOLD_DAYS", 0))


def get_or_create_referral_wallet(user):
    wallet, _ = ReferralWallet.objects.get_or_create(user=user)
    return wallet


def attribute_referral(new_user, referral_code):
    """Create the permanent referrer -> player relationship at registration.

    Enforces: valid + APPROVED referrer, no self-referral, first-valid-wins
    (a user already referred is never re-attributed). Safe no-op on any failure
    so registration never breaks because of a bad ref code.
    """
    if not referral_code:
        return None
    code = str(referral_code).strip()
    if not code:
        return None
    try:
        referrer = Referrer.objects.select_related("user").get(
            referral_code=code, status=Referrer.Status.APPROVED
        )
    except Referrer.DoesNotExist:
        return None

    # Self-referral protection (spec section 7).
    if referrer.user_id == new_user.id:
        return None

    # First-valid-wins / permanent: never overwrite an existing relationship.
    if Referral.objects.filter(referred_user=new_user).exists():
        return None

    return Referral.objects.create(
        referrer=referrer,
        referred_user=new_user,
        referral_code=code,
        status=Referral.Status.ACTIVE,
    )


@db_tx.atomic
def accrue_commission(
    referred_user,
    platform_fee,
    *,
    source_transaction=None,
    related_match=None,
    related_tournament=None,
):
    """Record referral commission for a realised platform fee.

    Idempotent: at most one ledger row per source transaction, or per
    (match, referred_user) / (tournament, referred_user) pair when no explicit
    transaction is supplied. Returns the ledger entry, or None when the player
    has no active referrer or nothing is owed.
    """
    referral = (
        Referral.objects.select_related("referrer", "referrer__user")
        .filter(referred_user=referred_user, status=Referral.Status.ACTIVE)
        .first()
    )
    if referral is None:
        return None

    referrer = referral.referrer
    if referrer.status != Referrer.Status.APPROVED:
        return None
    if referrer.user_id == getattr(referred_user, "id", referred_user):
        return None  # self-referral guard (defensive)

    # Idempotency guards.
    if source_transaction is not None:
        if ReferralCommissionLedger.objects.filter(
            transaction=source_transaction
        ).exists():
            return None
    else:
        dup = ReferralCommissionLedger.objects.filter(
            referred_user=referred_user,
            status__in=[
                ReferralCommissionLedger.Status.PENDING,
                ReferralCommissionLedger.Status.AVAILABLE,
            ],
        )
        if related_match is not None:
            dup = dup.filter(related_match=related_match)
        elif related_tournament is not None:
            dup = dup.filter(related_tournament=related_tournament)
        else:
            dup = dup.none()
        if dup.exists():
            return None

    rate = referrer.effective_rate()
    commission = _q(Decimal(platform_fee) * rate / Decimal("100"))
    if commission <= 0:
        return None

    status = (
        ReferralCommissionLedger.Status.AVAILABLE
        if _hold_days() <= 0
        else ReferralCommissionLedger.Status.PENDING
    )

    entry = ReferralCommissionLedger.objects.create(
        referrer=referrer,
        referred_user=referred_user,
        transaction=source_transaction,
        related_match=related_match,
        related_tournament=related_tournament,
        platform_fee=_q(platform_fee),
        commission_rate=rate,
        commission_amount=commission,
        status=status,
    )

    wallet = ReferralWallet.objects.select_for_update().filter(
        user=referrer.user
    ).first()
    if wallet is None:
        wallet = ReferralWallet.objects.create(user=referrer.user)
        wallet = ReferralWallet.objects.select_for_update().get(pk=wallet.pk)
    wallet.balance = (wallet.balance or Decimal("0.00")) + commission
    wallet.save(update_fields=["balance", "updated_at"])

    logger.info(
        "Referral commission accrued: referrer=%s amount=%s status=%s",
        referrer.referral_code,
        commission,
        status,
    )
    return entry


@db_tx.atomic
def reverse_commission(*, related_match=None, related_tournament=None, source_transaction=None):
    """Reverse still-outstanding commission for a refunded/disputed source (spec 6).

    Writes a negative mirror ledger row (status REVERSED) for each affected
    PENDING/AVAILABLE entry, marks the original CANCELLED, and decrements the
    wallet. The original row is never deleted. Returns the count reversed.
    """
    qs = ReferralCommissionLedger.objects.select_for_update().filter(
        status__in=[
            ReferralCommissionLedger.Status.PENDING,
            ReferralCommissionLedger.Status.AVAILABLE,
        ]
    )
    if source_transaction is not None:
        qs = qs.filter(transaction=source_transaction)
    elif related_match is not None:
        qs = qs.filter(related_match=related_match)
    elif related_tournament is not None:
        qs = qs.filter(related_tournament=related_tournament)
    else:
        return 0

    count = 0
    for original in qs:
        ReferralCommissionLedger.objects.create(
            referrer=original.referrer,
            referred_user=original.referred_user,
            related_match=original.related_match,
            related_tournament=original.related_tournament,
            platform_fee=original.platform_fee,
            commission_rate=original.commission_rate,
            commission_amount=-original.commission_amount,
            status=ReferralCommissionLedger.Status.REVERSED,
            reversal_of=original,
        )
        original.status = ReferralCommissionLedger.Status.CANCELLED
        original.save(update_fields=["status", "updated_at"])

        wallet = ReferralWallet.objects.select_for_update().get(
            user=original.referrer.user
        )
        wallet.balance = (wallet.balance or Decimal("0.00")) - original.commission_amount
        wallet.save(update_fields=["balance", "updated_at"])
        count += 1

    if count:
        logger.info("Reversed %s referral commission entries", count)
    return count


def release_pending_commissions():
    """Promote PENDING -> AVAILABLE once the hold window has elapsed."""
    hold = _hold_days()
    qs = ReferralCommissionLedger.objects.filter(
        status=ReferralCommissionLedger.Status.PENDING
    )
    if hold > 0:
        cutoff = timezone.now() - timezone.timedelta(days=hold)
        qs = qs.filter(created_at__lte=cutoff)
    return qs.update(status=ReferralCommissionLedger.Status.AVAILABLE)
