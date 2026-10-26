from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from wallet.models import Transaction, Wallet

from .models import Match


@transaction.atomic
def settle_match(match, *, winner=None, draw=False):
    """Atomically complete a match, credit its payout, and accrue referrals."""
    if draw == (winner is not None):
        raise ValidationError("Choose exactly one of a winner or a draw.")

    match_id = getattr(match, "pk", match)
    locked_match = (
        Match.objects.select_for_update(of=("self",))
        .select_related("creator", "joiner", "winner")
        .get(pk=match_id)
    )
    if locked_match.status == "COMPLETED":
        if locked_match.winner_id != getattr(winner, "pk", winner):
            raise ValidationError("This match has already been settled differently.")
        return locked_match
    if locked_match.status not in ("JOINED", "DISPUTED"):
        raise ValidationError("Only joined or disputed matches can be settled.")
    if locked_match.joiner_id is None:
        raise ValidationError("A match needs two players before it can be settled.")

    if winner is not None:
        winner_id = getattr(winner, "pk", winner)
        if winner_id not in (locked_match.creator_id, locked_match.joiner_id):
            raise ValidationError("The winner must be a participant in the match.")
        winner = (
            locked_match.creator
            if winner_id == locked_match.creator_id
            else locked_match.joiner
        )

        wallet, _ = Wallet.objects.get_or_create(user=winner)
        wallet = Wallet.objects.select_for_update().get(pk=wallet.pk)
        amount = Decimal(locked_match.winnings)
        wallet.balance += amount
        wallet.save(update_fields=["balance"])
        Transaction.objects.create(
            wallet=wallet,
            amount=amount,
            transaction_type="MATCH_WINNINGS",
            description=(
                f"Winnings from {locked_match.get_game_display()} match "
                f"{locked_match.joining_code}"
            ),
            related_match=locked_match,
        )
        locked_match.winner = winner
    else:
        refund_amount = Decimal(locked_match.amount) * Decimal("0.9")
        for player, opponent in (
            (locked_match.creator, locked_match.joiner),
            (locked_match.joiner, locked_match.creator),
        ):
            wallet, _ = Wallet.objects.get_or_create(user=player)
            wallet = Wallet.objects.select_for_update().get(pk=wallet.pk)
            wallet.balance += refund_amount
            wallet.save(update_fields=["balance"])
            Transaction.objects.create(
                wallet=wallet,
                amount=refund_amount,
                transaction_type="MATCH_DRAW_RETURN",
                description=(
                    f"Return from draw in {locked_match.get_game_display()} "
                    f"match against {opponent.username} for ZMW {locked_match.amount}"
                ),
                related_match=locked_match,
            )
        locked_match.winner = None

    locked_match.status = "COMPLETED"
    locked_match.save(update_fields=["status", "winner"])

    from referrals.services import accrue_commission, PLATFORM_FEE_RATE

    platform_fee = Decimal(locked_match.amount) * PLATFORM_FEE_RATE
    for player in (locked_match.creator, locked_match.joiner):
        accrue_commission(
            referred_user=player,
            platform_fee=platform_fee,
            related_match=locked_match,
        )

    return locked_match
