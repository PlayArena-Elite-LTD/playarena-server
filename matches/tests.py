from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from matches.models import Match, MatchResult
from panel.models import Dispute
from referrals.models import Referral, Referrer, ReferralCommissionLedger, ReferralWallet
from wallet.models import Transaction, Wallet


class MatchResultSubmissionTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.creator = User.objects.create_user(
            username='creator',
            email='creator@test.com',
            password='pass1234',
        )
        self.joiner = User.objects.create_user(
            username='joiner',
            email='joiner@test.com',
            password='pass1234',
        )
        for user in (self.creator, self.joiner):
            wallet, _ = Wallet.objects.get_or_create(user=user)
            wallet.balance = Decimal('100.00')
            wallet.save(update_fields=['balance'])

        self.match = Match.objects.create(
            creator=self.creator,
            joiner=self.joiner,
            game='FIFA_MOBILE',
            device='MOBILE',
            privacy='PUBLIC',
            amount=10,
            status='JOINED',
        )

    def test_completed_match_records_and_displays_winner_name(self):
        self.client.force_login(self.creator)
        self.client.post(
            reverse('submit_match_result', args=[self.match.id]),
            {'submission': 'WON'},
        )

        self.client.force_login(self.joiner)
        self.client.post(
            reverse('submit_match_result', args=[self.match.id]),
            {'submission': 'LOST'},
        )

        self.match.refresh_from_db()
        self.assertEqual(self.match.status, 'COMPLETED')
        self.assertEqual(self.match.winner, self.creator)

        response = self.client.get(reverse('match_detail', args=[self.match.id]))
        self.assertContains(response, 'Winner:')
        self.assertContains(response, self.creator.username)

    def test_match_detail_shows_joiner_name_in_participant_header(self):
        self.client.force_login(self.creator)

        response = self.client.get(reverse('match_detail', args=[self.match.id]))

        self.assertContains(response, 'Joiner: joiner')

    def test_query_admin_button_hidden_before_result_wait_period(self):
        self.client.force_login(self.creator)
        self.client.post(
            reverse('submit_match_result', args=[self.match.id]),
            {'submission': 'WON'},
        )
        match_result = MatchResult.objects.get(match=self.match)
        match_result.creator_submission_time = timezone.now() - timedelta(hours=23)
        match_result.save(update_fields=['creator_submission_time'])

        response = self.client.get(reverse('match_detail', args=[self.match.id]))

        self.assertNotContains(response, 'Query Admin')

    def test_query_admin_button_shows_after_unanswered_result_wait_period(self):
        self.client.force_login(self.creator)
        self.client.post(
            reverse('submit_match_result', args=[self.match.id]),
            {'submission': 'WON'},
        )
        match_result = MatchResult.objects.get(match=self.match)
        match_result.creator_submission_time = timezone.now() - timedelta(hours=25)
        match_result.save(update_fields=['creator_submission_time'])

        response = self.client.get(reverse('match_detail', args=[self.match.id]))

        self.assertContains(response, 'Query Admin')

    def test_query_unanswered_result_creates_dispute_for_admin_review(self):
        self.client.force_login(self.creator)
        self.client.post(
            reverse('submit_match_result', args=[self.match.id]),
            {'submission': 'WON'},
        )
        match_result = MatchResult.objects.get(match=self.match)
        match_result.creator_submission_time = timezone.now() - timedelta(hours=25)
        match_result.save(update_fields=['creator_submission_time'])

        response = self.client.post(reverse('query_unanswered_result', args=[self.match.id]))

        self.assertRedirects(response, reverse('match_detail', args=[self.match.id]))
        self.match.refresh_from_db()
        self.assertEqual(self.match.status, 'DISPUTED')
        self.assertTrue(Dispute.objects.filter(match=self.match, status='OPEN').exists())

    def test_non_submitter_cannot_query_unanswered_result(self):
        self.client.force_login(self.creator)
        self.client.post(
            reverse('submit_match_result', args=[self.match.id]),
            {'submission': 'WON'},
        )
        match_result = MatchResult.objects.get(match=self.match)
        match_result.creator_submission_time = timezone.now() - timedelta(hours=25)
        match_result.save(update_fields=['creator_submission_time'])

        self.client.force_login(self.joiner)
        response = self.client.post(reverse('query_unanswered_result', args=[self.match.id]))

        self.assertRedirects(response, reverse('match_detail', args=[self.match.id]))
        self.match.refresh_from_db()
        self.assertEqual(self.match.status, 'JOINED')
        self.assertFalse(Dispute.objects.filter(match=self.match).exists())


class MatchSettlementTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.creator = User.objects.create_user(
            username='settle_creator',
            email='settle_creator@test.com',
            password='pass1234',
        )
        self.joiner = User.objects.create_user(
            username='settle_joiner',
            email='settle_joiner@test.com',
            password='pass1234',
        )
        self.match = Match.objects.create(
            creator=self.creator,
            joiner=self.joiner,
            game='FIFA_MOBILE',
            device='MOBILE',
            privacy='PUBLIC',
            amount=10,
            status='JOINED',
        )
        self.referrer = Referrer.objects.create(
            user=self.creator,
            referral_code='SETTLE',
            status=Referrer.Status.APPROVED,
            commission_rate=Decimal('30.00'),
        )
        Referral.objects.create(
            referrer=self.referrer,
            referred_user=self.joiner,
            referral_code=self.referrer.referral_code,
        )

    def test_winner_settlement_pays_and_accrues_once(self):
        from matches.settlement import settle_match

        settle_match(self.match, winner=self.creator)
        settle_match(self.match, winner=self.creator)

        self.match.refresh_from_db()
        self.assertEqual(self.match.status, 'COMPLETED')
        self.assertEqual(self.match.winner, self.creator)
        self.assertEqual(
            Transaction.objects.filter(
                related_match=self.match,
                transaction_type='MATCH_WINNINGS',
            ).count(),
            1,
        )
        entry = ReferralCommissionLedger.objects.get(
            related_match=self.match,
            referred_user=self.joiner,
        )
        self.assertEqual(entry.commission_amount, Decimal('0.30'))
        self.assertEqual(
            ReferralWallet.objects.get(user=self.creator).balance,
            Decimal('0.30'),
        )

    def test_draw_settlement_returns_stakes_and_accrues_commission(self):
        from matches.settlement import settle_match

        settle_match(self.match, draw=True)

        self.match.refresh_from_db()
        self.assertEqual(self.match.status, 'COMPLETED')
        self.assertIsNone(self.match.winner)
        self.assertEqual(
            Transaction.objects.filter(
                related_match=self.match,
                transaction_type='MATCH_DRAW_RETURN',
            ).count(),
            2,
        )
        self.assertEqual(
            ReferralCommissionLedger.objects.get(
                related_match=self.match,
                referred_user=self.joiner,
            ).commission_amount,
            Decimal('0.30'),
        )
