"""Atomic organisation-tournament platform-fee settlement helpers."""
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP

from django.db import transaction
from django.utils import timezone

from .models import (
    ORGANISATION_TOURNAMENT_PLATFORM_FEE_PERCENT,
    Tournament,
    TournamentFeeSettlement,
    TournamentRegistration,
)

CENT = Decimal("0.01")


def _registration_fee_allocations(registrations, gross_pool, fee_total):
    """Allocate the rounded tournament-wide fee across entries exactly.

    Floors each proportional entry fee to cents, then distributes the remaining
    cents by largest fractional remainder (stable registration-id tie-break).
    Therefore allocated fees sum exactly to the single pool-level calculation.
    """
    allocations = []
    allocated_total = Decimal("0.00")
    percent = ORGANISATION_TOURNAMENT_PLATFORM_FEE_PERCENT

    for registration in registrations:
        exact_fee = Decimal(registration.amount_paid) * percent / Decimal("100")
        base_fee = exact_fee.quantize(CENT, rounding=ROUND_DOWN)
        allocations.append([registration, base_fee, exact_fee - base_fee])
        allocated_total += base_fee

    remaining_cents = int((fee_total - allocated_total) / CENT)
    allocations.sort(key=lambda row: (-row[2], row[0].pk))
    for index in range(remaining_cents):
        allocations[index][1] += CENT

    return {registration.pk: fee for registration, fee, _ in allocations}


@transaction.atomic
def confirm_full_tournament(tournament):
    """Reserve the 10% pool fee once and move a full tournament to READY_TO_START.

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
    fee_total = (
        gross_pool
        * ORGANISATION_TOURNAMENT_PLATFORM_FEE_PERCENT
        / Decimal("100")
    ).quantize(CENT, rounding=ROUND_HALF_UP)
    net_pool = gross_pool - fee_total
    allocations = _registration_fee_allocations(
        registrations,
        gross_pool,
        fee_total,
    )

    for registration in registrations:
        fee = allocations[registration.pk]
        registration.platform_fee = fee
        registration.prize_contribution = Decimal(registration.amount_paid) - fee
        registration.save(update_fields=["platform_fee", "prize_contribution"])

    settlement_values = {
        "gross_pool": gross_pool,
        "platform_fee": fee_total,
        "net_prize_pool": net_pool,
        "fee_percent": ORGANISATION_TOURNAMENT_PLATFORM_FEE_PERCENT,
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

    tournament.platform_fee_percent = ORGANISATION_TOURNAMENT_PLATFORM_FEE_PERCENT
    tournament.status = "READY_TO_START"
    tournament.save(update_fields=["platform_fee_percent", "status"])
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
        registration.prize_contribution = registration.amount_paid
        registration.save(update_fields=["platform_fee", "prize_contribution"])
