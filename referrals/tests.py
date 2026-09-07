"""Tests for the referral program service layer and attribution rules."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from .models import (
    Referral,
    Referrer,
    ReferralCommissionLedger,
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

    def test_wallet_exposes_min_withdrawal(self):
        resp = self.client.get("/api/referrals/wallet/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("min_withdrawal", resp.data)
        self.assertIn("available_balance", resp.data)

    def test_withdrawal_below_minimum_rejected(self):
        Referrer.objects.create(
            user=self.user, referral_code="apiuser", status=Referrer.Status.APPROVED
        )
        resp = self.client.post("/api/referrals/withdrawals/", {"amount": "5.00"})
        self.assertEqual(resp.status_code, 400)

    def test_withdrawal_over_available_rejected(self):
        Referrer.objects.create(
            user=self.user, referral_code="apiuser", status=Referrer.Status.APPROVED
        )
        resp = self.client.post("/api/referrals/withdrawals/", {"amount": "100.00"})
        self.assertEqual(resp.status_code, 400)


@override_settings(REFERRAL_COMMISSION_HOLD_DAYS=0)
class WithdrawalReservationTests(TestCase):
    def setUp(self):
        from decimal import Decimal as D
        self.ref_user = make_user("wdref")
        self.referrer = Referrer.objects.create(
            user=self.ref_user, referral_code="WDREF", status=Referrer.Status.APPROVED,
            commission_rate=D("30.00"),
        )
        self.player = make_user("wdplayer")
        services.attribute_referral(self.player, "WDREF")
        # 3 x K10 fee -> 3 x K3 = K9 available
        for _ in range(3):
            m = _make_match(self.ref_user, self.player)
            services.accrue_commission(self.player, __import__("decimal").Decimal("10.00"), related_match=m)

    def test_pending_withdrawal_reserves_available(self):
        from decimal import Decimal as D
        from .models import ReferralWallet, ReferralWithdrawal
        wallet = ReferralWallet.objects.get(user=self.ref_user)
        self.assertEqual(wallet.available_balance, D("9.00"))
        ReferralWithdrawal.objects.create(referrer=self.referrer, amount=D("5.00"))
        self.assertEqual(wallet.available_balance, D("4.00"))

    def test_rejected_withdrawal_frees_available(self):
        from decimal import Decimal as D
        from .models import ReferralWallet, ReferralWithdrawal
        wd = ReferralWithdrawal.objects.create(referrer=self.referrer, amount=D("5.00"))
        wallet = ReferralWallet.objects.get(user=self.ref_user)
        self.assertEqual(wallet.available_balance, D("4.00"))
        wd.status = ReferralWithdrawal.Status.REJECTED
        wd.save()
        self.assertEqual(wallet.available_balance, D("9.00"))
