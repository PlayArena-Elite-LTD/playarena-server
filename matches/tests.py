from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from matches.models import Match
from wallet.models import Wallet


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
