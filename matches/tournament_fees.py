"""Atomic PlayArena platform-fee and tournament organiser-earnings settlement."""
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP

from django.db import transaction
from django.utils import timezone

from .models import Tournament, TournamentFeeSettlement, TournamentRegistration
from wallet.models import PlatformTransaction, PlatformWallet

CENT = Decimal("0.01")
PLATFORM_FEE_PERCENT = Decimal("10.00")


def _registration_fee_allocations(registrations, fee_total, gross_pool):
    """Allocate a rounded tournament-wide amount proportionally across entries.

    Floors each proportional entry fee to cents, then distributes the remaining
    cents by largest fractional remainder (stable registration-id tie-break).
    Therefore allocated amounts sum exactly to the pool-level calculation.
    """
    if gross_pool == 0:
        return {registration.pk: Decimal("0.00") for registration in registrations}

    allocations = []
    allocated_total = Decimal("0.00")
    for registration in registrations:
        exact_fee = Decimal(registration.amount_paid) * fee_total / gross_pool
        base_fee = exact_fee.quantize(CENT, rounding=ROUND_DOWN)
        allocations.append([registration, base_fee, exact_fee - base_fee])
        allocated_total += base_fee

    remaining_cents = int((fee_total - allocated_total) / CENT)
    allocations.sort(key=lambda row: (-row[2], row[0].pk))
    for index in range(remaining_cents):
        allocations[index][1] += CENT

    return {registration.pk: fee for registration, fee, _ in allocations}


def allocate_payout_withholdings(payout_amounts, fee_total):
    """Split a total organiser fee proportionally over scheduled prize payouts."""
    total_payouts = sum(payout_amounts.values(), Decimal("0.00"))
    if fee_total > total_payouts:
        raise ValueError("Scheduled prize payouts cannot cover organiser earnings.")
    if total_payouts == 0:
        if fee_total:
            raise ValueError("Organiser earnings cannot be collected without prize payouts.")
        return {position: Decimal("0.00") for position in payout_amounts}

    rows = []
    allocated_total = Decimal("0.00")
    for position, amount in payout_amounts.items():
        exact_fee = amount * fee_total / total_payouts
        base_fee = exact_fee.quantize(CENT, rounding=ROUND_DOWN)
        rows.append([position, base_fee, exact_fee - base_fee])
        allocated_total += base_fee

    remaining_cents = int((fee_total - allocated_total) / CENT)
    rows.sort(key=lambda row: (-row[2], row[0]))
    for index in range(remaining_cents):
        rows[index][1] += CENT

    return {position: fee for position, fee, _ in rows}


@transaction.atomic
def confirm_full_tournament(tournament):
    """Reserve the platform and organiser shares once for a full tournament.

    The caller should already hold a row lock on the tournament. Repeated calls
    return the existing reservation and do not create another settlement.
    """
    tournament = Tournament.objects.select_for_update().get(pk=tournament.pk)
    registrations = list(
        TournamentRegistration.objects.select_for_update()
        .filter(
            tournament=tournament,
            status=TournamentRegistration.Status.REGISTERED,
        )
        .order_by("pk")
    )
    if len(registrations) < tournament.max_players:
        return None

    existing = TournamentFeeSettlement.objects.filter(
        tournament=tournament
    ).first()
    if existing and existing.status in (
        TournamentFeeSettlement.Status.RESERVED,
        TournamentFeeSettlement.Status.RECOGNIZED,
    ):
        if tournament.status != "READY_TO_START":
            tournament.status = "READY_TO_START"
            tournament.save(update_fields=["status"])
        return existing
    if existing and existing.status == TournamentFeeSettlement.Status.REFUNDED:
        raise ValueError("A refunded tournament settlement cannot be reopened.")

    gross_pool = sum(
        (Decimal(registration.amount_paid) for registration in registrations),
        Decimal("0.00"),
    ).quantize(CENT)
    fee_percent = PLATFORM_FEE_PERCENT
    fee_total = (gross_pool * fee_percent / Decimal("100")).quantize(
        CENT, rounding=ROUND_HALF_UP
    )
    organiser_fee_percent = Decimal(tournament.organiser_fee_percent)
    organiser_fee_total = (
        (gross_pool - fee_total) * organiser_fee_percent / Decimal("100")
    ).quantize(CENT, rounding=ROUND_HALF_UP)
    net_pool = gross_pool - fee_total
    platform_allocations = _registration_fee_allocations(
        registrations, fee_total, gross_pool
    )

    for registration in registrations:
        platform_fee = platform_allocations[registration.pk]
        registration.platform_fee = platform_fee
        registration.organiser_fee = Decimal("0.00")
        registration.prize_contribution = Decimal(registration.amount_paid) - platform_fee
        registration.save(
            update_fields=["platform_fee", "organiser_fee", "prize_contribution"]
        )

    settlement_values = {
        "gross_pool": gross_pool,
        "platform_fee": fee_total,
        "organiser_fee": organiser_fee_total,
        "net_prize_pool": net_pool,
        "fee_percent": fee_percent,
        "organiser_fee_percent": organiser_fee_percent,
        "status": TournamentFeeSettlement.Status.RESERVED,
        "recognized_at": None,
        "reversed_at": None,
    }
    if existing:
        for field, value in settlement_values.items():
            setattr(existing, field, value)
        existing.save(update_fields=[*settlement_values.keys()])
        settlement = existing
    else:
        settlement = TournamentFeeSettlement.objects.create(
            tournament=tournament,
            **settlement_values,
        )

    tournament.status = "READY_TO_START"
    tournament.save(update_fields=["status"])
    return settlement


@transaction.atomic
def recognize_tournament_fee(tournament):
    """Recognize the reserved fee when a full tournament actually starts."""
    settlement = TournamentFeeSettlement.objects.select_for_update().get(
        tournament=tournament
    )
    if settlement.status == TournamentFeeSettlement.Status.RECOGNIZED:
        return settlement
    if settlement.status != TournamentFeeSettlement.Status.RESERVED:
        raise ValueError("Only a reserved tournament fee can be recognized.")

    if settlement.platform_fee > 0:
        platform_wallet, _created = PlatformWallet.objects.get_or_create(pk=1)
        platform_wallet = PlatformWallet.objects.select_for_update().get(pk=platform_wallet.pk)
        PlatformTransaction.objects.create(
            wallet=platform_wallet,
            fee_settlement=settlement,
            amount=settlement.platform_fee,
            description=(
                f"PlayArena fee for tournament #{settlement.tournament_id} "
                f"({settlement.fee_percent}%)"
            ),
        )
        platform_wallet.balance += settlement.platform_fee
        platform_wallet.save(update_fields=["balance"])

    settlement.status = TournamentFeeSettlement.Status.RECOGNIZED
    settlement.recognized_at = timezone.now()
    settlement.save(update_fields=["status", "recognized_at"])
    return settlement


@transaction.atomic
def reverse_tournament_fee(tournament, *, refunded):
    """Invalidate a reservation or reverse recognized revenue on cancellation."""
    settlement = TournamentFeeSettlement.objects.select_for_update().filter(
        tournament=tournament
    ).first()
    if settlement is None:
        return None
    if settlement.status in (
        TournamentFeeSettlement.Status.VOID,
        TournamentFeeSettlement.Status.REFUNDED,
    ):
        return settlement

    settlement.status = (
        TournamentFeeSettlement.Status.REFUNDED
        if refunded
        else TournamentFeeSettlement.Status.VOID
    )
    settlement.reversed_at = timezone.now()
    settlement.save(update_fields=["status", "reversed_at"])
    return settlement


def clear_reserved_entry_split(tournament):
    """Restore active pre-launch entries to gross escrow after a participant leaves."""
    registrations = tournament.registrations.filter(
        status=TournamentRegistration.Status.REGISTERED
    )
    for registration in registrations:
        registration.platform_fee = Decimal("0.00")
        registration.organiser_fee = Decimal("0.00")
        registration.prize_contribution = registration.amount_paid
        registration.save(
            update_fields=["platform_fee", "organiser_fee", "prize_contribution"]
        )
