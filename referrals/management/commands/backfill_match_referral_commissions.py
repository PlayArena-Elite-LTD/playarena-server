from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count

from matches.models import Match
from referrals.models import Referral, ReferralCommissionLedger, Referrer
from referrals.services import PLATFORM_FEE_RATE, accrue_commission
from wallet.models import Transaction


class Command(BaseCommand):
    help = (
        "Backfill referral commissions for completed matches. Defaults to a "
        "dry run; pass --commit to create ledger entries and referral balances."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--commit",
            action="store_true",
            help="Create the missing commissions instead of reporting a dry run.",
        )

    def handle(self, *args, **options):
        referrals_by_player = defaultdict(list)
        for referral in Referral.objects.filter(
            status=Referral.Status.ACTIVE,
            referrer__status=Referrer.Status.APPROVED,
        ).select_related("referrer"):
            referrals_by_player[referral.referred_user_id].append(referral)

        existing = set(
            ReferralCommissionLedger.objects.filter(
                related_match__isnull=False,
            ).values_list("related_match_id", "referred_user_id")
        )
        settlement_times = {}
        settled_transactions = Transaction.objects.filter(
            transaction_type__in=("MATCH_WINNINGS", "MATCH_DRAW_RETURN"),
            related_match__status="COMPLETED",
        ).order_by("created_at")
        for settled_transaction in settled_transactions.iterator():
            settlement_times.setdefault(
                settled_transaction.related_match_id,
                settled_transaction.created_at,
            )

        completed_draw_ids = set(
            Transaction.objects.filter(
                transaction_type="MATCH_DRAW_RETURN",
                related_match__status="COMPLETED",
            )
            .values("related_match_id")
            .annotate(player_count=Count("wallet__user_id", distinct=True))
            .filter(player_count__gte=2)
            .values_list("related_match_id", flat=True)
        )

        candidates = []
        skipped_post_settlement_attribution = 0
        for match in Match.objects.filter(status="COMPLETED").iterator():
            if match.winner_id is None and match.pk not in completed_draw_ids:
                continue
            for player_id in {match.creator_id, match.joiner_id} - {None}:
                for referral in referrals_by_player.get(player_id, ()):
                    if (match.pk, player_id) in existing:
                        continue
                    settled_at = settlement_times.get(match.pk, match.created_at)
                    if referral.created_at > settled_at:
                        skipped_post_settlement_attribution += 1
                        continue
                    platform_fee = Decimal(match.amount) * PLATFORM_FEE_RATE
                    commission = (
                        platform_fee
                        * referral.referrer.effective_rate()
                        / Decimal("100")
                    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                    if commission > 0:
                        candidates.append(
                            (match.pk, player_id, platform_fee, commission)
                        )

        total = sum((row[3] for row in candidates), Decimal("0.00"))
        mode = "Committing" if options["commit"] else "Dry run"
        self.stdout.write(
            f"{mode}: {len(candidates)} missing commission(s), "
            f"ZMW {total:.2f} total."
        )
        if skipped_post_settlement_attribution:
            self.stdout.write(
                f"Skipped {skipped_post_settlement_attribution} match/player "
                "pair(s) where referral attribution was created after settlement."
            )
        if not options["commit"]:
            self.stdout.write("No records were changed. Re-run with --commit to apply.")
            return

        created = 0
        credited = Decimal("0.00")
        with transaction.atomic():
            for match_id, player_id, platform_fee, expected_amount in candidates:
                locked_match = Match.objects.select_for_update().get(pk=match_id)
                if ReferralCommissionLedger.objects.filter(
                    related_match=locked_match,
                    referred_user_id=player_id,
                ).exists():
                    continue
                entry = accrue_commission(
                    referred_user=player_id,
                    platform_fee=platform_fee,
                    related_match=locked_match,
                )
                if entry is not None:
                    created += 1
                    credited += entry.commission_amount
                    if entry.commission_amount != expected_amount:
                        raise RuntimeError(
                            f"Commission changed while backfilling match {match_id}: "
                            f"expected {expected_amount}, got {entry.commission_amount}."
                        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Created {created} commission(s), credited ZMW {credited:.2f} "
                "to referral wallets."
            )
        )
