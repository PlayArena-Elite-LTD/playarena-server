"""Tests for the referral program service layer and attribution rules."""
from io import StringIO
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase, override_settings

from matches.models import Match
from wallet.models import Transaction, Wallet

from .models import (
    Referral,
    Referrer,
    ReferralCommissionLedger,
    ReferralTransfer,
    ReferralWallet,
)
from . import services

User = get_user_model()


def make_user(username):
    return User.objects.create_user(
        username=username, email=f"{username}@example.com", password="pw12345!"
    )



class AttributionTests(TestCase):
    def setUp(self):
        self.ref_user = make_user("kosamu")
        self.referrer = Referrer.objects.create(
            user=self.ref_user, referral_code="KOSAMU", status=Referrer.Status.APPROVED
        )

    def test_valid_attribution_creates_permanent_relationship(self):
        player = make_user("player1")
        rel = services.attribute_referral(player, "KOSAMU")
        self.assertIsNotNone(rel)
        self.assertEqual(rel.referrer, self.referrer)
        self.assertEqual(rel.referred_user, player)
        self.assertEqual(rel.status, Referral.Status.ACTIVE)

    def test_self_referral_blocked(self):
        rel = services.attribute_referral(self.ref_user, "KOSAMU")
        self.assertIsNone(rel)
        self.assertFalse(Referral.objects.filter(referred_user=self.ref_user).exists())

    def test_first_valid_referral_wins_and_is_permanent(self):
        other_user = make_user("otherref")
        Referrer.objects.create(
            user=other_user, referral_code="OTHER", status=Referrer.Status.APPROVED
        )
        player = make_user("player2")
        first = services.attribute_referral(player, "KOSAMU")
        second = services.attribute_referral(player, "OTHER")
        self.assertIsNotNone(first)
        self.assertIsNone(second)  # cannot overwrite
        self.assertEqual(
            Referral.objects.get(referred_user=player).referrer, self.referrer
        )

    def test_invalid_code_is_noop(self):
        player = make_user("player3")
        self.assertIsNone(services.attribute_referral(player, "NOPE"))

    def test_unapproved_referrer_is_noop(self):
        pending_user = make_user("pending")
        Referrer.objects.create(
            user=pending_user, referral_code="PENDING", status=Referrer.Status.PENDING
        )
        player = make_user("player4")
        self.assertIsNone(services.attribute_referral(player, "PENDING"))


@override_settings(REFERRAL_COMMISSION_HOLD_DAYS=0)
class AccrualTests(TestCase):
    def setUp(self):
        self.ref_user = make_user("earner")
        self.referrer = Referrer.objects.create(
            user=self.ref_user,
            referral_code="EARNER",
            status=Referrer.Status.APPROVED,
            commission_rate=Decimal("30.00"),
        )
        self.player = make_user("refplayer")
        services.attribute_referral(self.player, "EARNER")

    def test_commission_math_30pct_of_platform_fee(self):
        # Player stakes K100 -> platform fee = K10 -> commission = 30% = K3.00
        entry = services.accrue_commission(self.player, Decimal("10.00"))
        self.assertIsNotNone(entry)
        self.assertEqual(entry.commission_amount, Decimal("3.00"))
        self.assertEqual(entry.platform_fee, Decimal("10.00"))
        self.assertEqual(entry.commission_rate, Decimal("30.00"))
        self.assertEqual(entry.status, ReferralCommissionLedger.Status.AVAILABLE)

    def test_wallet_credited_on_accrual(self):
        services.accrue_commission(self.player, Decimal("10.00"))
        wallet = ReferralWallet.objects.get(user=self.ref_user)
        self.assertEqual(wallet.balance, Decimal("3.00"))
        self.assertEqual(wallet.available_balance, Decimal("3.00"))

    def test_no_referrer_returns_none(self):
        stranger = make_user("stranger")
        self.assertIsNone(services.accrue_commission(stranger, Decimal("10.00")))

    def test_suspended_referrer_no_commission(self):
        self.referrer.status = Referrer.Status.SUSPENDED
        self.referrer.save()
        self.assertIsNone(services.accrue_commission(self.player, Decimal("10.00")))

    def test_idempotent_by_match(self):
        from matches.models import Match
        match = _make_match(self.ref_user, self.player)
        first = services.accrue_commission(
            self.player, Decimal("10.00"), related_match=match
        )
        second = services.accrue_commission(
            self.player, Decimal("10.00"), related_match=match
        )
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(
            ReferralCommissionLedger.objects.filter(related_match=match).count(), 1
        )

    def test_rate_override(self):
        self.referrer.commission_rate = Decimal("50.00")
        self.referrer.save()
        entry = services.accrue_commission(self.player, Decimal("10.00"))
        self.assertEqual(entry.commission_amount, Decimal("5.00"))

    def test_zero_fee_no_commission(self):
        self.assertIsNone(services.accrue_commission(self.player, Decimal("0.00")))


@override_settings(REFERRAL_COMMISSION_HOLD_DAYS=0)
class ReversalTests(TestCase):
    def setUp(self):
        self.ref_user = make_user("rev")
        self.referrer = Referrer.objects.create(
            user=self.ref_user, referral_code="REV", status=Referrer.Status.APPROVED,
            commission_rate=Decimal("30.00"),
        )
        self.player = make_user("revplayer")
        services.attribute_referral(self.player, "REV")

    def test_reversal_writes_negative_mirror_and_decrements(self):
        match = _make_match(self.ref_user, self.player)
        services.accrue_commission(self.player, Decimal("10.00"), related_match=match)
        wallet = ReferralWallet.objects.get(user=self.ref_user)
        self.assertEqual(wallet.balance, Decimal("3.00"))

        count = services.reverse_commission(related_match=match)
        self.assertEqual(count, 1)
        wallet.refresh_from_db()
        self.assertEqual(wallet.balance, Decimal("0.00"))
        # original cancelled, negative mirror recorded, nothing deleted
        self.assertTrue(
            ReferralCommissionLedger.objects.filter(
                related_match=match, status=ReferralCommissionLedger.Status.CANCELLED
            ).exists()
        )
        mirror = ReferralCommissionLedger.objects.get(
            status=ReferralCommissionLedger.Status.REVERSED
        )
        self.assertEqual(mirror.commission_amount, Decimal("-3.00"))
        self.assertIsNotNone(mirror.reversal_of)

    def test_paid_commission_reversal_debits_normal_wallet_and_records_history(self):
        from wallet.models import Transaction, Wallet

        match = _make_match(self.ref_user, self.player)
        commission = services.accrue_commission(
            self.player,
            Decimal("10.00"),
            related_match=match,
        )
        services.transfer_commission_to_wallet(
            user=self.ref_user,
            commission_id=commission.pk,
        )

        normal_wallet = Wallet.objects.get(user=self.ref_user)
        # Model spending after the commission was transferred; the clawback
        # must recover the debt without corrupting the transaction ledger.
        normal_wallet.balance -= Decimal("2.00")
        normal_wallet.save(update_fields=["balance"])
        Transaction.objects.create(
            wallet=normal_wallet,
            amount=Decimal("-2.00"),
            transaction_type="OTHER",
            description="Test spend before commission clawback",
        )

        self.assertEqual(services.reverse_commission(related_match=match), 1)

        commission.refresh_from_db()
        normal_wallet.refresh_from_db()
        self.assertEqual(
            commission.status,
            ReferralCommissionLedger.Status.CANCELLED,
        )
        self.assertEqual(normal_wallet.balance, Decimal("-2.00"))
        self.assertTrue(normal_wallet.verify_balance_integrity()["is_valid"])
        self.assertEqual(
            commission.reversal_transaction.amount,
            Decimal("-3.00"),
        )
        self.assertEqual(
            commission.reversal_transaction.transaction_type,
            "REFERRAL_REVERSAL",
        )
        self.assertEqual(
            ReferralCommissionLedger.objects.get(
                reversal_of=commission
            ).commission_amount,
            Decimal("-3.00"),
        )

        # A repeated refund/reversal must not debit the wallet again.
        self.assertEqual(services.reverse_commission(related_match=match), 0)
        normal_wallet.refresh_from_db()
        self.assertEqual(normal_wallet.balance, Decimal("-2.00"))


@override_settings(REFERRAL_COMMISSION_HOLD_DAYS=7)
class HoldWindowTests(TestCase):
    def setUp(self):
        self.ref_user = make_user("holder")
        Referrer.objects.create(
            user=self.ref_user, referral_code="HOLD", status=Referrer.Status.APPROVED,
            commission_rate=Decimal("30.00"),
        )
        self.player = make_user("holdplayer")
        services.attribute_referral(self.player, "HOLD")

    def test_commission_pending_under_hold(self):
        entry = services.accrue_commission(self.player, Decimal("10.00"))
        self.assertEqual(entry.status, ReferralCommissionLedger.Status.PENDING)
        wallet = ReferralWallet.objects.get(user=self.ref_user)
        self.assertEqual(wallet.balance, Decimal("3.00"))
        self.assertEqual(wallet.available_balance, Decimal("0.00"))
        self.assertEqual(wallet.pending_balance, Decimal("3.00"))


@override_settings(REFERRAL_COMMISSION_HOLD_DAYS=0)
class TransferTests(TestCase):
    def setUp(self):
        self.ref_user = make_user("transferref")
        Referrer.objects.create(
            user=self.ref_user,
            referral_code="TRANSFERREF",
            status=Referrer.Status.APPROVED,
            commission_rate=Decimal("30.00"),
        )
        self.player = make_user("transferplayer")
        services.attribute_referral(self.player, "TRANSFERREF")
        self.commission = services.accrue_commission(
            self.player, Decimal("10.00")
        )

    def test_transfer_moves_exact_commission_once(self):
        transfer, created = services.transfer_commission_to_wallet(
            user=self.ref_user,
            commission_id=self.commission.pk,
        )

        self.assertTrue(created)
        self.assertEqual(transfer.amount, Decimal("3.00"))
        self.assertEqual(transfer.status, ReferralTransfer.Status.COMPLETED)
        self.assertEqual(transfer.wallet_transaction.amount, Decimal("3.00"))
        self.assertEqual(
            transfer.wallet_transaction.transaction_type,
            "REFERRAL_TRANSFER",
        )

        self.commission.refresh_from_db()
        referral_wallet = ReferralWallet.objects.get(user=self.ref_user)
        from wallet.models import Wallet
        normal_wallet = Wallet.objects.get(user=self.ref_user)
        self.assertEqual(self.commission.status, ReferralCommissionLedger.Status.PAID)
        self.assertEqual(referral_wallet.balance, Decimal("0.00"))
        self.assertEqual(normal_wallet.balance, Decimal("3.00"))
        self.assertTrue(normal_wallet.verify_balance_integrity()["is_valid"])

        repeated, created_again = services.transfer_commission_to_wallet(
            user=self.ref_user,
            commission_id=self.commission.pk,
        )
        self.assertFalse(created_again)
        self.assertEqual(repeated.pk, transfer.pk)
        normal_wallet.refresh_from_db()
        self.assertEqual(normal_wallet.transactions.count(), 1)

    def test_cannot_transfer_another_referrers_commission(self):
        other_user = make_user("nottransferref")
        with self.assertRaises(ValidationError):
            services.transfer_commission_to_wallet(
                user=other_user,
                commission_id=self.commission.pk,
            )
        self.assertEqual(other_user.wallet.balance, Decimal("0.00"))

    def test_inconsistent_referral_balance_blocks_transfer(self):
        wallet = ReferralWallet.objects.get(user=self.ref_user)
        wallet.balance = Decimal("99.00")
        wallet.save(update_fields=["balance"])

        with self.assertRaises(ValidationError):
            services.transfer_commission_to_wallet(
                user=self.ref_user,
                commission_id=self.commission.pk,
            )
        self.assertEqual(self.ref_user.wallet.balance, Decimal("0.00"))
        self.assertEqual(ReferralTransfer.objects.count(), 0)


def _make_match(creator, joiner, amount=100):
    from matches.models import Match
    return Match.objects.create(
        creator=creator,
        joiner=joiner,
        game="FIFA_MOBILE",
        device="MOBILE",
        privacy="PUBLIC",
        amount=amount,
        status="JOINED",
    )


class ReferralCommissionBackfillTests(TestCase):
    def test_backfill_is_dry_run_by_default_and_idempotent_on_commit(self):
        referrer_user = make_user("backfill_referrer")
        referred_user = make_user("backfill_referred")
        opponent = make_user("backfill_opponent")
        referrer = Referrer.objects.create(
            user=referrer_user,
            referral_code="BACKFILL",
            status=Referrer.Status.APPROVED,
            commission_rate=Decimal("30.00"),
        )
        Referral.objects.create(
            referrer=referrer,
            referred_user=referred_user,
            referral_code=referrer.referral_code,
        )
        match = Match.objects.create(
            creator=referred_user,
            joiner=opponent,
            winner=opponent,
            game="FIFA_MOBILE",
            device="MOBILE",
            privacy="PUBLIC",
            amount=10,
            status="COMPLETED",
        )

        output = StringIO()
        call_command("backfill_match_referral_commissions", stdout=output)
        self.assertIn(
            "Dry run: 1 missing commission(s), ZMW 0.30 total.",
            output.getvalue(),
        )
        self.assertFalse(
            ReferralCommissionLedger.objects.filter(related_match=match).exists()
        )

        call_command(
            "backfill_match_referral_commissions",
            commit=True,
            stdout=StringIO(),
        )
        call_command(
            "backfill_match_referral_commissions",
            commit=True,
            stdout=StringIO(),
        )

        self.assertEqual(
            ReferralCommissionLedger.objects.filter(related_match=match).count(),
            1,
        )
        self.assertEqual(
            ReferralWallet.objects.get(user=referrer_user).balance,
            Decimal("0.30"),
        )

    def test_backfill_uses_settlement_time_not_match_creation_time(self):
        referrer_user = make_user("late_backfill_referrer")
        referred_user = make_user("late_backfill_referred")
        opponent = make_user("late_backfill_opponent")
        match = Match.objects.create(
            creator=referred_user,
            joiner=opponent,
            game="FIFA_MOBILE",
            device="MOBILE",
            privacy="PUBLIC",
            amount=10,
            status="JOINED",
        )
        referrer = Referrer.objects.create(
            user=referrer_user,
            referral_code="LATEBACKFILL",
            status=Referrer.Status.APPROVED,
            commission_rate=Decimal("30.00"),
        )
        Referral.objects.create(
            referrer=referrer,
            referred_user=referred_user,
            referral_code=referrer.referral_code,
        )
        match.status = "COMPLETED"
        match.winner = opponent
        match.save(update_fields=["status", "winner"])
        wallet, _ = Wallet.objects.get_or_create(user=opponent)
        Transaction.objects.create(
            wallet=wallet,
            amount=Decimal(match.winnings),
            transaction_type="MATCH_WINNINGS",
            description="Settled test match",
            related_match=match,
        )

        call_command(
            "backfill_match_referral_commissions",
            commit=True,
            stdout=StringIO(),
        )

        self.assertEqual(
            ReferralCommissionLedger.objects.filter(related_match=match).count(),
            1,
        )
        self.assertEqual(
            ReferralWallet.objects.get(user=referrer_user).balance,
            Decimal("0.30"),
        )


@override_settings(REFERRAL_COMMISSION_HOLD_DAYS=0)
class ReferralApiTests(TestCase):
    def setUp(self):
        from rest_framework.test import APIClient
        self.client = APIClient()
        self.user = make_user("apiuser")
        self.client.force_authenticate(user=self.user)

    def test_apply_creates_pending_referrer(self):
        resp = self.client.post("/api/referrals/apply/")
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["status"], Referrer.Status.PENDING)
        self.assertEqual(resp.data["referral_code"], "apiuser")

    def test_me_reports_non_referrer(self):
        resp = self.client.get("/api/referrals/me/")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.data["is_referrer"])

    def test_wallet_exposes_available_and_pending_balances(self):
        resp = self.client.get("/api/referrals/wallet/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("available_balance", resp.data)
        self.assertNotIn("min_withdrawal", resp.data)

    def test_transfer_endpoint_credits_only_owned_commission(self):
        Referrer.objects.create(
            user=self.user,
            referral_code="apiuser",
            status=Referrer.Status.APPROVED,
        )
        player = make_user("api_referred_player")
        services.attribute_referral(player, "apiuser")
        commission = services.accrue_commission(player, Decimal("10.00"))

        response = self.client.post(
            "/api/referrals/transfers/",
            {"commission_id": commission.pk},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["amount"], "3.00")
        from wallet.models import Wallet
        self.assertEqual(
            Wallet.objects.get(user=self.user).balance,
            Decimal("3.00"),
        )

    def test_transfer_endpoint_rejects_missing_commission(self):
        response = self.client.post(
            "/api/referrals/transfers/",
            {"commission_id": 999999},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
