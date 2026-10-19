"""Referral commission business logic.

Single choke point for every referral money movement so the hook sites stay
one-liners and the audit trail is guaranteed: no balance ever changes without a
corresponding immutable ledger row (spec section 5).
"""
import logging
from decimal import Decimal, ROUND_HALF_UP

from django.contrib.auth import get_user_model
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction as db_tx
from django.utils import timezone
from wallet.models import Transaction, Wallet

from .models import (
    Referral,
    Referrer,
    ReferralCommissionLedger,
    ReferralTransfer,
    ReferralWallet,
)

logger = logging.getLogger(__name__)

# The separate 1v1 match platform fee remains 10% of the transaction amount
# (the implicit 10% baked into match winnings = amount * 2 * 0.9). Tournament
# platform fees are fixed at 10%; organiser earnings are configured separately.
PLATFORM_FEE_RATE = Decimal("0.10")


def _q(amount):
    return Decimal(amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _hold_days():
    return int(getattr(settings, "REFERRAL_COMMISSION_HOLD_DAYS", 0))


def get_or_create_referral_wallet(user):
    wallet, _ = ReferralWallet.objects.get_or_create(user=user)
    return wallet


@db_tx.atomic
def attribute_referral(new_user, referral_code):
    """Create the permanent referrer -> player relationship at registration.

    Enforces: valid + APPROVED referrer, no self-referral, first-valid-wins
    (a user already referred is never re-attributed). Safe no-op on any failure
    so registration never breaks because of a bad ref code.
    """
    if not referral_code:
        return None
    new_user = get_user_model().objects.select_for_update().get(pk=new_user.pk)
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
    referred_user_id = getattr(referred_user, "pk", referred_user)
    referred_user = get_user_model().objects.select_for_update().get(
        pk=referred_user_id
    )

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
    if referrer.user_id == referred_user.pk:
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
        )
        if related_match is not None:
            dup = dup.filter(related_match=related_match)
        elif related_tournament is not None:
            dup = dup.filter(related_tournament=related_tournament)
        else:
            dup = dup.none()
        if dup.exists():
            return None

    platform_fee = Decimal(str(platform_fee))
    if not platform_fee.is_finite() or platform_fee < 0:
        raise ValidationError("Platform fee must be a finite, non-negative amount.")
    if platform_fee > Decimal("9999999999.99"):
        raise ValidationError("Platform fee exceeds the supported amount limit.")

    rate = referrer.effective_rate()
    if not rate.is_finite() or rate < 0 or rate > 100:
        raise ValidationError("Referrer's commission rate is invalid.")
    commission = _q(platform_fee * rate / Decimal("100"))
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

    wallet, _ = ReferralWallet.objects.get_or_create(user=referrer.user)
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
def transfer_commission_to_wallet(*, user, commission_id):
    """Atomically move one AVAILABLE commission into the user's normal wallet.

    The commission row serializes repeat requests for the same commission;
    both wallet rows are locked before balances change. Repeating a successful
    request returns the existing transfer without crediting the wallet again.
    """
    try:
        commission = (
            ReferralCommissionLedger.objects.select_for_update()
            .select_related("referrer", "referrer__user")
            .get(pk=commission_id)
        )
    except ReferralCommissionLedger.DoesNotExist as exc:
        raise ValidationError("Commission was not found.") from exc

    if commission.referrer.user_id != user.pk:
        raise ValidationError("This commission does not belong to you.")

    existing_transfer = ReferralTransfer.objects.filter(
        commission=commission
    ).first()
    if commission.status == ReferralCommissionLedger.Status.PAID:
        if (
            existing_transfer is not None
            and existing_transfer.status == ReferralTransfer.Status.COMPLETED
            and existing_transfer.wallet_transaction_id is not None
        ):
            return existing_transfer, False
        raise ValidationError(
            "Commission is marked paid but has no completed wallet transfer."
        )
    if commission.status != ReferralCommissionLedger.Status.AVAILABLE:
        raise ValidationError("Only available commissions can be transferred.")
    if existing_transfer is not None:
        raise ValidationError("A transfer already exists for this commission.")
    if commission.commission_amount <= 0:
        raise ValidationError("Commission amount must be positive.")

    referrer = Referrer.objects.select_for_update().get(
        pk=commission.referrer_id
    )
    if referrer.status != Referrer.Status.APPROVED:
        raise ValidationError("Only approved referrers can transfer commissions.")

    referral_wallet, _ = ReferralWallet.objects.get_or_create(user=referrer.user)
    referral_wallet = ReferralWallet.objects.select_for_update().get(
        pk=referral_wallet.pk
    )

    expected_balance = (
        referral_wallet.pending_balance + referral_wallet.available_balance
    )
    if referral_wallet.balance != expected_balance:
        raise ValidationError(
            "Referral wallet balance does not match its ledger; transfer blocked."
        )
    if referral_wallet.available_balance < commission.commission_amount:
        raise ValidationError("Referral wallet has insufficient available balance.")

    normal_wallet, _ = Wallet.objects.get_or_create(user=referrer.user)
    normal_wallet = Wallet.objects.select_for_update().get(pk=normal_wallet.pk)
    if not normal_wallet.verify_balance_integrity()["is_valid"]:
        raise ValidationError(
            "Normal wallet balance does not match its transaction history; transfer blocked."
        )
    amount = commission.commission_amount
    if amount > Decimal("99999999.99"):
        raise ValidationError(
            "Commission exceeds the normal wallet transaction amount limit."
        )
    new_balance = (normal_wallet.balance or Decimal("0.00")) + amount
    # wallet.Wallet.balance and wallet.Transaction.amount are Decimal(10, 2).
    if new_balance > Decimal("99999999.99"):
        raise ValidationError("Transfer would exceed the normal wallet balance limit.")

    normal_wallet.balance = new_balance
    normal_wallet.save(update_fields=["balance"])

    wallet_transaction = Transaction.objects.create(
        wallet=normal_wallet,
        amount=amount,
        transaction_type="REFERRAL_TRANSFER",
        description=(
            f"Referral commission transfer #{commission.pk}"
        ),
        related_match=commission.related_match,
        related_tournament=commission.related_tournament,
    )

    transfer = ReferralTransfer.objects.create(
        referrer=referrer,
        commission=commission,
        wallet_transaction=wallet_transaction,
        amount=amount,
        status=ReferralTransfer.Status.COMPLETED,
        transfer_reference=f"REF-COMMISSION-{commission.pk}",
        completed_at=timezone.now(),
    )

    referral_wallet.balance -= amount
    referral_wallet.save(update_fields=["balance", "updated_at"])
    commission.status = ReferralCommissionLedger.Status.PAID
    commission.save(update_fields=["status", "updated_at"])

    logger.info(
        "Referral commission transferred internally: referrer=%s commission=%s amount=%s",
        commission.referrer.referral_code,
        commission.pk,
        amount,
    )
    return transfer, True


@db_tx.atomic
def reverse_commission(*, related_match=None, related_tournament=None, source_transaction=None):
    """Reverse unsettled or already-transferred commission for a source.

    Unsettled commissions are removed from the referral wallet. Paid
    commissions are clawed back from the normal wallet with a negative wallet
    transaction; that can make the normal balance negative, so future credits
    first cover the debt. Each affected commission receives a negative mirror
    ledger row and is marked CANCELLED. Returns the number reversed.
    """
    qs = ReferralCommissionLedger.objects.select_for_update().filter(
        status__in=[
            ReferralCommissionLedger.Status.PENDING,
            ReferralCommissionLedger.Status.AVAILABLE,
            ReferralCommissionLedger.Status.PAID,
        ]
    ).order_by("pk")
    if source_transaction is not None:
        qs = qs.filter(transaction=source_transaction)
    elif related_match is not None:
        qs = qs.filter(related_match=related_match)
    elif related_tournament is not None:
        qs = qs.filter(related_tournament=related_tournament)
    else:
        return 0

    originals = list(qs)
    if not originals:
        return 0

    referrer_ids = sorted({entry.referrer_id for entry in originals})
    referrers = {
        referrer.pk: referrer
        for referrer in Referrer.objects.select_for_update()
        .filter(pk__in=referrer_ids)
        .order_by("pk")
    }
    user_ids = sorted({referrer.user_id for referrer in referrers.values()})

    referral_wallets = {}
    normal_wallets = {}
    for user_id in user_ids:
        referral_wallet, _ = ReferralWallet.objects.get_or_create(
            user_id=user_id
        )
        referral_wallets[user_id] = referral_wallet
    for user_id in user_ids:
        normal_wallet, _ = Wallet.objects.get_or_create(user_id=user_id)
        normal_wallets[user_id] = normal_wallet

    referral_wallets = {
        wallet.user_id: wallet
        for wallet in ReferralWallet.objects.select_for_update()
        .filter(user_id__in=user_ids)
        .order_by("user_id")
    }
    normal_wallets = {
        wallet.user_id: wallet
        for wallet in Wallet.objects.select_for_update()
        .filter(user_id__in=user_ids)
        .order_by("user_id")
    }

    for wallet in normal_wallets.values():
        if not wallet.verify_balance_integrity()["is_valid"]:
            raise ValidationError(
                "Normal wallet balance does not match its transaction history; "
                "commission reversal blocked."
            )

    for wallet in referral_wallets.values():
        expected = wallet.pending_balance + wallet.available_balance
        if wallet.balance != expected:
            raise ValidationError(
                "Referral wallet balance does not match its ledger; "
                "commission reversal blocked."
            )

    count = 0
    for original in originals:
        reversal_transaction = None
        amount = original.commission_amount
        if amount <= 0:
            raise ValidationError(
                f"Commission {original.pk} has an invalid non-positive amount."
            )

        if original.status == ReferralCommissionLedger.Status.PAID:
            if amount > Decimal("99999999.99"):
                raise ValidationError(
                    f"Commission {original.pk} exceeds the normal wallet "
                    "transaction amount limit."
                )
            transfer = ReferralTransfer.objects.select_for_update().filter(
                commission=original,
                status=ReferralTransfer.Status.COMPLETED,
            ).select_related("wallet_transaction").first()
            if (
                transfer is None
                or transfer.wallet_transaction_id is None
                or transfer.amount != amount
                or transfer.wallet_transaction.amount != amount
                or transfer.wallet_transaction.transaction_type != "REFERRAL_TRANSFER"
                or transfer.wallet_transaction.wallet.user_id != original.referrer.user_id
            ):
                raise ValidationError(
                    f"Paid commission {original.pk} has no matching completed "
                    "wallet transfer; reversal blocked."
                )
            wallet = normal_wallets[original.referrer.user_id]
            new_balance = wallet.balance - amount
            if abs(new_balance) > Decimal("99999999.99"):
                raise ValidationError(
                    f"Reversing commission {original.pk} exceeds the normal "
                    "wallet balance limit."
                )
            wallet.balance = new_balance
            wallet.save(update_fields=["balance"])
            reversal_transaction = Transaction.objects.create(
                wallet=wallet,
                amount=-amount,
                transaction_type="REFERRAL_REVERSAL",
                description=f"Reversal of referral commission #{original.pk}",
                related_match=original.related_match,
                related_tournament=original.related_tournament,
            )
        else:
            wallet = referral_wallets[original.referrer.user_id]
            wallet.balance -= amount
            if wallet.balance < 0:
                raise ValidationError(
                    f"Referral wallet would become negative reversing commission "
                    f"{original.pk}."
                )
            wallet.save(update_fields=["balance", "updated_at"])

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
        original.reversal_transaction = reversal_transaction
        original.save(
            update_fields=["status", "reversal_transaction", "updated_at"]
        )
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
