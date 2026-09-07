"""Promote PENDING referral commissions to AVAILABLE once the hold has elapsed.

Run on a schedule (e.g. daily) when REFERRAL_COMMISSION_HOLD_DAYS > 0. With a
hold of 0 commissions are already AVAILABLE on settlement, so this is a no-op.
"""
from django.core.management.base import BaseCommand

from referrals import services


class Command(BaseCommand):
    help = "Release PENDING referral commissions that have cleared the hold window."

    def handle(self, *args, **options):
        released = services.release_pending_commissions()
        self.stdout.write(self.style.SUCCESS(f"Released {released} commission(s)."))
