
from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase, APIClient

from matches.models import Match
from wallet.models import Wallet, Transaction


class MatchApiTests(APITestCase):
    def setUp(self):
        self.client = APIClient()
        User = get_user_model()
        self.creator = User.objects.create_user(username='creator', email='creator@test.com', password='pass1234')
        self.joiner = User.objects.create_user(username='joiner', email='joiner@test.com', password='pass1234')
        self.other = User.objects.create_user(username='other', email='other@test.com', password='pass1234')

        self.creator_wallet, _ = Wallet.objects.get_or_create(user=self.creator)
        self.creator_wallet.balance = Decimal('100.00')
        self.creator_wallet.save(update_fields=['balance'])

        self.joiner_wallet, _ = Wallet.objects.get_or_create(user=self.joiner)
        self.joiner_wallet.balance = Decimal('100.00')
        self.joiner_wallet.save(update_fields=['balance'])

    def test_create_match_deducts_wallet_and_creates_transaction(self):
        self.client.force_authenticate(self.creator)
        payload = {
            'game': 'FIFA_MOBILE',
            'device': 'MOBILE',
            'privacy': 'PUBLIC',
            'amount': 10,
        }
        response = self.client.post('/api/matches/create/', payload, format='json')
        self.assertEqual(response.status_code, 201)

        match = Match.objects.get(id=response.data['match']['id'])
        self.creator_wallet.refresh_from_db()

        self.assertEqual(match.creator, self.creator)
        self.assertEqual(match.amount, 10)
        self.assertEqual(match.status, 'OPEN')
        self.assertEqual(self.creator_wallet.balance, Decimal('90.00'))
        self.assertTrue(Transaction.objects.filter(related_match=match, transaction_type='MATCH_CREATION').exists())

    def test_join_match_updates_status_and_wallet(self):
        match = Match.objects.create(
            creator=self.creator,
            game='FIFA_MOBILE',
            device='MOBILE',
            privacy='PUBLIC',
            amount=10,
        )

        self.client.force_authenticate(self.joiner)
        response = self.client.post('/api/matches/join/', {'joining_code': match.joining_code}, format='json')
        self.assertEqual(response.status_code, 200)

        match.refresh_from_db()
        self.joiner_wallet.refresh_from_db()

        self.assertEqual(match.status, 'JOINED')
        self.assertEqual(match.joiner, self.joiner)
        self.assertEqual(self.joiner_wallet.balance, Decimal('90.00'))
        self.assertTrue(Transaction.objects.filter(related_match=match, transaction_type='MATCH_JOINING').exists())

    def test_match_detail_private_requires_participant(self):
        match = Match.objects.create(
            creator=self.creator,
            game='FIFA_MOBILE',
            device='MOBILE',
            privacy='PRIVATE',
            amount=10,
        )

        self.client.force_authenticate(self.other)
        response = self.client.get(f'/api/matches/{match.id}/')
        self.assertEqual(response.status_code, 403)

    def test_submit_result_completes_match_and_awards_winner(self):
        self.client.force_authenticate(self.creator)
        create_response = self.client.post(
            '/api/matches/create/',
            {'game': 'FIFA_MOBILE', 'device': 'MOBILE', 'privacy': 'PUBLIC', 'amount': 10},
            format='json',
        )
        match_id = create_response.data['match']['id']
        match = Match.objects.get(id=match_id)

        self.client.force_authenticate(self.joiner)
        join_response = self.client.post('/api/matches/join/', {'joining_code': match.joining_code}, format='json')
        self.assertEqual(join_response.status_code, 200)

        self.client.force_authenticate(self.creator)
        response = self.client.post(f'/api/matches/{match.id}/submit-result/', {'submission': 'WON'}, format='json')
        self.assertEqual(response.status_code, 200)

        self.client.force_authenticate(self.joiner)
        response = self.client.post(f'/api/matches/{match.id}/submit-result/', {'submission': 'LOST'}, format='json')
        self.assertEqual(response.status_code, 200)

        match.refresh_from_db()
        self.creator_wallet.refresh_from_db()

        self.assertEqual(match.status, 'COMPLETED')
        self.assertEqual(match.winner, self.creator)
        self.assertTrue(Transaction.objects.filter(related_match=match, transaction_type='MATCH_WINNINGS').exists())
        expected_balance = Decimal('90.00') + Decimal(match.winnings)
        self.assertEqual(self.creator_wallet.balance, expected_balance)

    def test_cancel_match_refunds_creator(self):
        self.client.force_authenticate(self.creator)
        create_response = self.client.post(
            '/api/matches/create/',
            {'game': 'FIFA_MOBILE', 'device': 'MOBILE', 'privacy': 'PUBLIC', 'amount': 10},
            format='json',
        )
        match_id = create_response.data['match']['id']

        response = self.client.post(f'/api/matches/{match_id}/cancel/')
        self.assertEqual(response.status_code, 200)

        self.creator_wallet.refresh_from_db()
        self.assertFalse(Match.objects.filter(id=match_id).exists())
        self.assertEqual(self.creator_wallet.balance, Decimal('100.00'))
        self.assertTrue(Transaction.objects.filter(transaction_type='MATCH_REFUND').exists())
