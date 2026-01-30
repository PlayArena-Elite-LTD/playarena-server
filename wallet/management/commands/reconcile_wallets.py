from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction

from wallet.models import Wallet


class Command(BaseCommand):
    help = "Reconcile wallet balances against transaction totals."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report discrepancies without fixing them",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Limit the number of wallets to reconcile",
        )
        parser.add_argument(
            "--user-id",
            type=int,
            default=None,
            help="Reconcile a single user's wallet by user ID",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        limit = options["limit"]
        user_id = options["user_id"]

        wallets = Wallet.objects.all().select_related("user")
        if user_id:
            wallets = wallets.filter(user_id=user_id)
        if limit:
            wallets = wallets[:limit]

        total_wallets = wallets.count()
        if total_wallets == 0:
            self.stdout.write(self.style.WARNING("No wallets found to reconcile."))
            return

        self.stdout.write(
            f"Starting reconciliation at {timezone.now().isoformat()} "
            f"(wallets: {total_wallets}, dry_run={dry_run})"
        )

        discrepancies = []
        fixed_count = 0

        for wallet in wallets:
            result = wallet.verify_balance_integrity()
            if result["is_valid"]:
                continue

            discrepancies.append({
                "wallet_id": wallet.id,
                "user": wallet.user.username if wallet.user else None,
                "expected": result["expected_balance"],
                "actual": result["actual_balance"],
                "discrepancy": result["discrepancy"],
                "transaction_count": result["transaction_count"],
            })

            if dry_run:
                continue

            with transaction.atomic():
                wallet.recalculate_balance()
                fixed_count += 1

        self.stdout.write(self.style.WARNING("Discrepancies found: {}".format(len(discrepancies))))
        for item in discrepancies:
            self.stdout.write(
                "Wallet {wallet_id} ({user}): expected={expected}, actual={actual}, "
                "discrepancy={discrepancy}, tx_count={transaction_count}".format(**item)
            )

        if not dry_run:
            self.stdout.write(self.style.SUCCESS(f"Wallets fixed: {fixed_count}"))
