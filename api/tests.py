import base64
import hashlib
import hmac
import json
import re
from decimal import Decimal
from requests import HTTPError
from unittest.mock import patch

from django.core import mail
from django.core.cache import cache
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase, APIClient
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken
from rest_framework_simplejwt.tokens import RefreshToken

from alert.models import Notification, ReadNotification
from accounts.models import Organisation, OrganisationMembership
from matches.models import Match, Tournament
from messenger.models import Message, ReadMessage
from panel.models import Dispute
from wallet.models import Wallet, Transaction
from wallet.models import Deposit
from services.payments.lipila_gateway import LipilaGateway
from services.payments.lipila_service import LipilaService

User = get_user_model()


class LipilaServiceTests(TestCase):
    def test_mobile_money_retries_api_v1_when_old_collection_route_is_missing(self):
        class FakeResponse:
            def __init__(self, status_code, body):
                self.status_code = status_code
                self._body = body
                self.text = json.dumps(body)
                self.content = self.text.encode()
                self.ok = 200 <= status_code < 300

            def json(self):
                return self._body

            def raise_for_status(self):
                if not self.ok:
                    raise HTTPError(f'{self.status_code} error', response=self)

        responses = [
            FakeResponse(404, {
                'message': 'Cannot POST /collections/mobile-money',
                'error': 'Not Found',
                'statusCode': 404,
            }),
            FakeResponse(200, {
                'status': 'Pending',
                'identifier': 'LPLXC-123',
            }),
        ]
        posted_urls = []

        def fake_post(url, **kwargs):
            posted_urls.append(url)
            return responses.pop(0)

        service = LipilaService(
            secret_key='secret',
            base_url='https://api.lipila.io',
            mobile_money_path='/collections/mobile-money',
        )

        with patch('services.payments.lipila_service.requests.post', side_effect=fake_post):
            result = service.initiate_mobile_money(
                reference_id='DEP_122_1782728784',
                amount=20.0,
                account_number='260971234567',
                currency='ZMW',
                narration='Deposit for payer',
                idempotency_key='dep-122',
            )

        self.assertEqual(result['identifier'], 'LPLXC-123')
        self.assertEqual(posted_urls, [
            'https://api.lipila.io/collections/mobile-money',
            'https://api.lipila.io/api/v1/collections/mobile-money',
        ])

    def test_disbursement_defaults_to_base_url(self):
        class FakeResponse:
            status_code = 200
            text = '{"status": "Pending", "identifier": "WDR-123"}'
            content = text.encode()
            ok = True

            def json(self):
                return {'status': 'Pending', 'identifier': 'WDR-123'}

            def raise_for_status(self):
                return None

        posted_urls = []
        posted_headers = []

        def fake_post(url, **kwargs):
            posted_urls.append(url)
            posted_headers.append(kwargs['headers'])
            return FakeResponse()

        service = LipilaService(
            secret_key='secret',
            base_url='https://api.lipila.dev',
        )

        with patch('services.payments.lipila_service.requests.post', side_effect=fake_post):
            result = service.disburse_mobile_money(
                reference_id='WDR_1',
                amount=20.0,
                account_number='260971234567',
                currency='ZMW',
            )

        self.assertEqual(result['identifier'], 'WDR-123')
        self.assertEqual(posted_urls, [
            'https://api.lipila.dev/api/v1/disbursements/mobile-money',
        ])
        self.assertEqual(posted_headers[0]['x-api-key'], 'secret')
        self.assertNotIn('Authorization', posted_headers[0])

    def test_disbursement_raises_unauthorized_with_api_key_only(self):
        class FakeResponse:
            def __init__(self, status_code, body):
                self.status_code = status_code
                self._body = body
                self.text = json.dumps(body)
                self.content = self.text.encode()
                self.ok = 200 <= status_code < 300

            def json(self):
                return self._body

            def raise_for_status(self):
                if not self.ok:
                    raise HTTPError(f'{self.status_code} error', response=self)

        response = FakeResponse(401, {})
        posted_headers = []

        def fake_post(url, **kwargs):
            posted_headers.append(kwargs['headers'])
            return response

        service = LipilaService(
            secret_key='secret',
            base_url='https://api.lipila.dev',
        )

        with patch('services.payments.lipila_service.requests.post', side_effect=fake_post):
            with self.assertRaises(HTTPError):
                service.disburse_mobile_money(
                    reference_id='WDR_1',
                    amount=20.0,
                    account_number='260971234567',
                    currency='ZMW',
                )

        self.assertEqual(len(posted_headers), 1)
        self.assertNotIn('Authorization', posted_headers[0])
        self.assertEqual(posted_headers[0]['x-api-key'], 'secret')


class LipilaGatewayVerifyTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='payer',
            email='payer@test.com',
            password='pass1234',
        )
        self.wallet, _ = Wallet.objects.get_or_create(user=self.user)

    @staticmethod
    def _signed_webhook_request(payload, secret, *, timestamp=None, signatures=None):
        raw_body = json.dumps(payload).encode()
        webhook_id = '3f2a1b4c-5d6e-7f8a-9b0c-1d2e3f4a5b6c'
        webhook_timestamp = str(timestamp or int(timezone.now().timestamp()))
        signed_payload = (
            webhook_id.encode()
            + b'.'
            + webhook_timestamp.encode()
            + b'.'
            + raw_body
        )
        signature = 'v1,' + base64.b64encode(
            hmac.new(secret, signed_payload, hashlib.sha256).digest()
        ).decode()
        return RequestFactory().post(
            '/api/payments/lipila/webhook/',
            data=raw_body,
            content_type='application/json',
            headers={
                'webhook-id': webhook_id,
                'webhook-timestamp': webhook_timestamp,
                'webhook-signature': signatures or signature,
            },
        )

    def test_webhook_signature_uses_lipila_standard_webhooks_format(self):
        key = b'0123456789abcdef0123456789abcdef'
        request = self._signed_webhook_request({'status': 'Successful'}, key)

        with override_settings(LIPILA_WEBHOOK_SECRET=base64.b64encode(key).decode()):
            self.assertTrue(
                LipilaGateway._verify_webhook_signature(request, request.body)
            )

    def test_webhook_signature_accepts_matching_signature_during_key_rotation(self):
        key = b'0123456789abcdef0123456789abcdef'
        request = self._signed_webhook_request({'status': 'Successful'}, key)
        valid_signature = request.META['HTTP_WEBHOOK_SIGNATURE']
        request.META['HTTP_WEBHOOK_SIGNATURE'] = f'v1,invalid {valid_signature}'

        with override_settings(LIPILA_WEBHOOK_SECRET=base64.b64encode(key).decode()):
            self.assertTrue(
                LipilaGateway._verify_webhook_signature(request, request.body)
            )

    def test_webhook_signature_rejects_stale_timestamp(self):
        key = b'0123456789abcdef0123456789abcdef'
        stale_timestamp = int(timezone.now().timestamp()) - 301
        request = self._signed_webhook_request(
            {'status': 'Successful'}, key, timestamp=stale_timestamp
        )

        with override_settings(LIPILA_WEBHOOK_SECRET=base64.b64encode(key).decode()):
            self.assertFalse(
                LipilaGateway._verify_webhook_signature(request, request.body)
            )

    def test_verify_payment_checks_provider_transaction_after_pending_reference(self):
        deposit = Deposit.objects.create(
            user=self.user,
            wallet=self.wallet,
            amount=Decimal('1.00'),
            status='PROCESSING',
            payment_method='LIPILA_MOMO',
            payment_provider='lipila',
            provider_payment_status='Pending',
            payment_reference='DEP_4_1780478276',
            provider_transaction_id='LPLXC-20260603-091757-624-2954',
            transaction_id='LPLXC-20260603-091757-624-2954',
        )

        class FakeLipilaService:
            def __init__(self):
                self.refs = []

            def get_transaction_status(self, reference_id):
                self.refs.append(reference_id)
                if reference_id == 'DEP_4_1780478276':
                    return {'status': 'Pending', 'referenceId': reference_id}
                return {
                    'data': {
                        'status': 'Successful',
                        'transactionId': 'LPLXC-20260603-091757-624-2954',
                    }
                }

        service = FakeLipilaService()
        result = LipilaGateway(service=service).verify_payment(deposit)

        self.assertEqual(
            service.refs,
            ['DEP_4_1780478276', 'LPLXC-20260603-091757-624-2954'],
        )
        self.assertTrue(result.success)
        self.assertEqual(result.payment_status, 'Successful')
        self.assertEqual(result.provider_transaction_id, 'LPLXC-20260603-091757-624-2954')

    def test_webhook_matches_deposit_by_identifier_and_stores_lipila_reference(self):
        deposit = Deposit.objects.create(
            user=self.user,
            wallet=self.wallet,
            amount=Decimal('1.75'),
            status='PROCESSING',
            payment_method='LIPILA_MOMO',
            payment_provider='lipila',
            provider_payment_status='Pending',
            payment_reference='DEP_5_1780478276',
        )
        payload = {
            'referenceId': 'b4c9a8f1-7c4d-4b3e-bc8a-5d9e2b15f7a1',
            'currency': 'ZMW',
            'amount': 1.75,
            'accountNumber': '260971234567',
            'status': 'Successful',
            'paymentType': 'MTNMoney',
            'type': 'Collection',
            'identifier': 'DEP_5_1780478276',
            'message': 'Payment completed successfully.',
            'externalId': 'MP250000987654321',
            'referenceData': 'Payment for food',
        }
        request = RequestFactory().post(
            '/api/payments/lipila/webhook/',
            data=json.dumps(payload),
            content_type='application/json',
        )

        result = LipilaGateway().handle_webhook(request)

        deposit.refresh_from_db()
        self.wallet.refresh_from_db()
        self.assertTrue(result.processed)
        self.assertEqual(result.deposit_id, deposit.id)
        self.assertEqual(deposit.status, 'COMPLETED')
        self.assertEqual(deposit.provider_payment_status, 'Successful')
        self.assertEqual(deposit.provider_transaction_id, 'b4c9a8f1-7c4d-4b3e-bc8a-5d9e2b15f7a1')
        self.assertEqual(self.wallet.balance, Decimal('1.75'))

    def test_verify_payment_stays_pending_when_lipila_status_lookup_rejects_refs(self):
        deposit = Deposit.objects.create(
            user=self.user,
            wallet=self.wallet,
            amount=Decimal('1.00'),
            status='PROCESSING',
            payment_method='LIPILA_MOMO',
            payment_provider='lipila',
            provider_payment_status='Pending',
            payment_reference='DEP_38_1780478927',
            provider_transaction_id='LPLXC-20260603-092848-254-2478',
            transaction_id='LPLXC-20260603-092848-254-2478',
        )

        class FakeLipilaService:
            def get_transaction_status(self, reference_id):
                raise HTTPError(
                    f'400 Client Error: Bad Request for referenceId={reference_id}'
                )

        result = LipilaGateway(service=FakeLipilaService()).verify_payment(deposit)

        self.assertFalse(result.success)
        self.assertEqual(result.payment_status, 'Pending')
        self.assertEqual(result.message, 'Awaiting Lipila callback confirmation')


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

    def test_cancel_match_blocked_after_result_submitted(self):
        self.client.force_authenticate(self.creator)
        create_response = self.client.post(
            '/api/matches/create/',
            {'game': 'FIFA_MOBILE', 'device': 'MOBILE', 'privacy': 'PUBLIC', 'amount': 10},
            format='json',
        )
        match_id = create_response.data['match']['id']
        match = Match.objects.get(id=match_id)

        self.client.force_authenticate(self.joiner)
        self.client.post('/api/matches/join/', {'joining_code': match.joining_code}, format='json')

        self.client.force_authenticate(self.creator)
        response = self.client.post(f'/api/matches/{match.id}/submit-result/', {'submission': 'WON'}, format='json')
        self.assertEqual(response.status_code, 200)

        # Joiner tries to cancel after creator has already submitted a result.
        self.client.force_authenticate(self.joiner)
        response = self.client.post(f'/api/matches/{match.id}/cancel/')
        self.assertEqual(response.status_code, 400)

        match.refresh_from_db()
        self.joiner_wallet.refresh_from_db()
        self.assertEqual(match.status, 'JOINED')
        self.assertEqual(self.joiner_wallet.balance, Decimal('90.00'))


class OrganisationTournamentApiTests(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = User.objects.create_user(
            username='org-owner',
            email='org-owner@test.com',
            password='pass1234',
        )
        self.other_owner = User.objects.create_user(
            username='other-org-owner',
            email='other-org-owner@test.com',
            password='pass1234',
        )
        self.player = User.objects.create_user(
            username='player',
            email='player@test.com',
            password='pass1234',
        )
        self.organisation = Organisation.objects.create(
            owner=self.owner,
            name='Lusaka Esports Hub',
            contact_name='Martha Banda',
            email='hub@test.com',
            phone='+260971234567',
            organisation_type=Organisation.OrganisationType.TOURNAMENT_ORGANISER,
            city='Lusaka',
        )
        self.other_organisation = Organisation.objects.create(
            owner=self.other_owner,
            name='Copperbelt Arena',
            contact_name='Joseph Phiri',
            email='copperbelt@test.com',
            phone='+260961234567',
            organisation_type=Organisation.OrganisationType.GAMING_LOUNGE,
            city='Kitwe',
        )

    def test_organisation_owner_can_create_tournament(self):
        self.client.force_authenticate(self.owner)
        payload = {
            'name': 'Friday FC Knockout',
            'game': 'FIFA_MOBILE',
            'participation_amount': '25.00',
            'max_players': 32,
            'rules': 'Single elimination. Check in 15 minutes before start.',
            'start_date': '2026-08-09',
        }

        response = self.client.post('/api/organisations/tournaments/', payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        tournament = Tournament.objects.get(id=response.data['id'])
        self.assertEqual(tournament.organisation, self.organisation)
        self.assertEqual(tournament.game, 'FIFA_MOBILE')
        self.assertEqual(tournament.participation_amount, Decimal('25.00'))
        self.assertEqual(tournament.max_players, 32)
        self.assertEqual(tournament.status, 'OPEN')

    def test_regular_player_cannot_create_organisation_tournament(self):
        self.client.force_authenticate(self.player)
        payload = {
            'name': 'Unauthorised Tournament',
            'game': 'FIFA_MOBILE',
            'participation_amount': '25.00',
            'max_players': 16,
        }

        response = self.client.post('/api/organisations/tournaments/', payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(Tournament.objects.filter(name='Unauthorised Tournament').exists())

    def test_tournament_list_is_scoped_to_authenticated_organisation(self):
        own_tournament = Tournament.objects.create(
            organisation=self.organisation,
            name='Own Tournament',
            game='COD_MOBILE',
            participation_amount=Decimal('10.00'),
            max_players=16,
        )
        Tournament.objects.create(
            organisation=self.other_organisation,
            name='Other Tournament',
            game='PUBG_MOBILE',
            participation_amount=Decimal('20.00'),
            max_players=16,
        )

        self.client.force_authenticate(self.owner)
        response = self.client.get('/api/organisations/tournaments/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([item['id'] for item in response.data], [own_tournament.id])


class OrganisationMembershipApiTests(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = User.objects.create_user(
            username='membership-owner',
            email='membership-owner@test.com',
            password='pass1234',
        )
        self.player = User.objects.create_user(
            username='membership-player',
            email='membership-player@test.com',
            password='pass1234',
        )
        self.organisation = Organisation.objects.create(
            owner=self.owner,
            name='Lusaka Esports Hub',
            contact_name='Martha Banda',
            email='membership-hub@test.com',
            phone='+260971234567',
            organisation_type=Organisation.OrganisationType.TOURNAMENT_ORGANISER,
            city='Lusaka',
        )
        self.tournament = Tournament.objects.create(
            organisation=self.organisation,
            name='Members Only FC Cup',
            game='FIFA_MOBILE',
            participation_amount=Decimal('25.00'),
            max_players=32,
            status='OPEN',
        )

    def test_player_can_request_to_join_organisation(self):
        self.client.force_authenticate(self.player)

        response = self.client.post(f'/api/organisations/{self.organisation.id}/request-join/')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        membership = OrganisationMembership.objects.get(
            organisation=self.organisation,
            player=self.player,
        )
        self.assertEqual(membership.status, OrganisationMembership.Status.PENDING)

    def test_player_sees_membership_status_in_organisation_list(self):
        OrganisationMembership.objects.create(
            organisation=self.organisation,
            player=self.player,
            status=OrganisationMembership.Status.PENDING,
        )
        self.client.force_authenticate(self.player)

        response = self.client.get('/api/organisations/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data[0]['membership_status'], 'PENDING')

    def test_player_only_sees_organisation_tournaments_after_approval(self):
        self.client.force_authenticate(self.player)
        response = self.client.get('/api/player/tournaments/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

        membership = OrganisationMembership.objects.create(
            organisation=self.organisation,
            player=self.player,
            status=OrganisationMembership.Status.PENDING,
        )

        self.client.force_authenticate(self.owner)
        response = self.client.post(f'/api/organisations/membership-requests/{membership.id}/approve/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        membership.refresh_from_db()
        self.assertEqual(membership.status, OrganisationMembership.Status.APPROVED)

        self.client.force_authenticate(self.player)
        response = self.client.get('/api/player/tournaments/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([item['id'] for item in response.data], [self.tournament.id])


class GraphQLAPITests(APITestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='graphql_user',
            email='graphql@test.com',
            password='testpass123',
        )
        self.opponent = User.objects.create_user(
            username='opponent',
            email='opponent@test.com',
            password='testpass123',
        )
        self.other = User.objects.create_user(
            username='other_graphql',
            email='other_graphql@test.com',
            password='testpass123',
        )

        self.user.profile.first_name = 'Graph'
        self.user.profile.last_name = 'User'
        self.user.profile.save(update_fields=['first_name', 'last_name'])

        self.wallet, _created = Wallet.objects.get_or_create(user=self.user)
        self.wallet.balance = Decimal('125.50')
        self.wallet.save(update_fields=['balance'])
        self.opponent_wallet, _created = Wallet.objects.get_or_create(user=self.opponent)
        self.opponent_wallet.balance = Decimal('100.00')
        self.opponent_wallet.save(update_fields=['balance'])

        self.match = Match.objects.create(
            creator=self.user,
            joiner=self.opponent,
            game='FIFA_MOBILE',
            device='MOBILE',
            privacy='PUBLIC',
            amount=10,
            status='JOINED',
        )
        self.available_match = Match.objects.create(
            creator=self.opponent,
            game='CHESS_COM',
            device='MOBILE',
            privacy='PUBLIC',
            amount=5,
            status='OPEN',
        )
        Match.objects.create(
            creator=self.other,
            game='PUBG_MOBILE',
            device='MOBILE',
            privacy='PRIVATE',
            amount=20,
            status='OPEN',
        )
        self.transaction = Transaction.objects.create(
            wallet=self.wallet,
            amount=Decimal('125.50'),
            transaction_type='DEPOSIT',
            description='Initial balance',
            related_match=self.match,
        )

        self.token = str(RefreshToken.for_user(self.user).access_token)

    def graphql(self, query, variables=None, token=None):
        if token is False:
            self.client.credentials()
        elif token is not None:
            self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        else:
            self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token}')
        return self.client.post(
            '/api/graphql/',
            {'query': query, 'variables': variables or {}},
            format='json',
        )

    def test_me_wallet_and_transactions_use_bearer_jwt(self):
        response = self.graphql(
            '''
            query {
              me {
                id
                username
                email
                profile {
                  firstName
                  lastName
                }
              }
              wallet {
                id
                balance
              }
              transactions {
                id
                amount
                transactionType
                description
                isCredit
                relatedMatch {
                  id
                  game
                  creator {
                    username
                  }
                }
              }
            }
            '''
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertNotIn('errors', body)
        self.assertEqual(body['data']['me']['username'], self.user.username)
        self.assertEqual(body['data']['me']['email'], self.user.email)
        self.assertEqual(body['data']['me']['profile']['firstName'], 'Graph')
        self.assertEqual(body['data']['wallet']['balance'], '125.50')
        self.assertEqual(body['data']['transactions'][0]['transactionType'], 'DEPOSIT')
        self.assertTrue(body['data']['transactions'][0]['isCredit'])
        self.assertEqual(
            body['data']['transactions'][0]['relatedMatch']['creator']['username'],
            self.user.username,
        )

    def test_matches_support_filters_and_available_flag(self):
        response = self.graphql(
            '''
            query {
              matches(available: true) {
                id
                game
                status
                privacy
              }
            }
            '''
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertNotIn('errors', body)
        match_ids = {int(item['id']) for item in body['data']['matches']}
        self.assertEqual(match_ids, {self.available_match.id})
        self.assertEqual(body['data']['matches'][0]['status'], 'OPEN')
        self.assertEqual(body['data']['matches'][0]['privacy'], 'PUBLIC')

    def test_my_matches_only_returns_current_user_matches(self):
        response = self.graphql(
            '''
            query {
              myMatches {
                id
                game
                joiner {
                  username
                }
              }
            }
            '''
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertNotIn('errors', body)
        self.assertEqual([int(item['id']) for item in body['data']['myMatches']], [self.match.id])
        self.assertEqual(body['data']['myMatches'][0]['joiner']['username'], self.opponent.username)

    def test_authenticated_queries_reject_missing_token(self):
        self.client.credentials()
        response = self.client.post(
            '/api/graphql/',
            {'query': 'query { wallet { id balance } }'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertIn('errors', body)
        self.assertEqual(body['data'], None)
        self.assertEqual(body['errors'][0]['message'], 'Authentication required.')

    def test_auth_and_profile_mutations(self):
        response = self.graphql(
            '''
            mutation {
              register(
                username: "new_graphql_user",
                email: "new_graphql@test.com",
                password: "testpass123",
                passwordConfirm: "testpass123"
              ) {
                user { username email }
                access
                refresh
              }
            }
            ''',
            token=False,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertNotIn('errors', body)
        self.assertEqual(body['data']['register']['user']['username'], 'new_graphql_user')
        self.assertTrue(body['data']['register']['access'])

        response = self.graphql(
            '''
            mutation {
              tokenAuth(username: "new_graphql_user", password: "testpass123") {
                access
                refresh
              }
            }
            ''',
            token=False,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertNotIn('errors', body)
        self.assertTrue(body['data']['tokenAuth']['access'])

        response = self.graphql(
            '''
            mutation {
              updateProfile(firstName: "Updated", lastName: "Player") {
                username
                profile { firstName lastName }
              }
            }
            '''
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertNotIn('errors', body)
        self.assertEqual(body['data']['updateProfile']['profile']['firstName'], 'Updated')
        self.assertEqual(body['data']['updateProfile']['profile']['lastName'], 'Player')

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_password_reset_request_and_confirm_mutations(self):
        mail.outbox = []
        response = self.graphql(
            '''
            mutation {
              requestPasswordReset(email: "graphql@test.com") {
                message
              }
            }
            ''',
            token=False,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertNotIn('errors', body)
        self.assertEqual(len(mail.outbox), 1)
        reset_match = re.search(r'/accounts/reset/([^/]+)/([^/]+)/', mail.outbox[0].body)
        self.assertIsNotNone(reset_match)
        uid, reset_token = reset_match.groups()

        response = self.graphql(
            '''
            mutation Reset($uid: String!, $token: String!) {
              resetPasswordConfirm(
                uid: $uid,
                token: $token,
                newPassword: "newpass12345",
                newPasswordConfirm: "newpass12345"
              ) {
                message
              }
            }
            ''',
            variables={'uid': uid, 'token': reset_token},
            token=False,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertNotIn('errors', body)
        self.assertEqual(
            body['data']['resetPasswordConfirm']['message'],
            'Password has been reset successfully.',
        )
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('newpass12345'))

    def test_token_verify_refresh_rotation_and_logout_blacklist(self):
        response = self.graphql(
            '''
            mutation {
              tokenAuth(username: "graphql_user", password: "testpass123") {
                access
                refresh
              }
            }
            ''',
            token=False,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertNotIn('errors', body)
        access = body['data']['tokenAuth']['access']
        refresh = body['data']['tokenAuth']['refresh']

        response = self.graphql(
            '''
            mutation Verify($token: String!) {
              verifyToken(token: $token) {
                valid
                tokenType
                userId
              }
            }
            ''',
            variables={'token': access},
            token=False,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertNotIn('errors', body)
        self.assertTrue(body['data']['verifyToken']['valid'])
        self.assertEqual(body['data']['verifyToken']['tokenType'], 'access')
        self.assertEqual(int(body['data']['verifyToken']['userId']), self.user.id)

        response = self.graphql(
            '''
            mutation Refresh($refresh: String!) {
              refreshToken(refresh: $refresh) {
                access
                refresh
              }
            }
            ''',
            variables={'refresh': refresh},
            token=False,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertNotIn('errors', body)
        rotated_refresh = body['data']['refreshToken']['refresh']
        self.assertTrue(rotated_refresh)

        response = self.graphql(
            '''
            mutation Logout($refresh: String!) {
              logout(refresh: $refresh) {
                message
              }
            }
            ''',
            variables={'refresh': rotated_refresh},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertNotIn('errors', body)
        self.assertEqual(body['data']['logout']['message'], 'Logged out successfully.')
        self.assertTrue(BlacklistedToken.objects.exists())

        response = self.graphql(
            '''
            mutation Verify($token: String!) {
              verifyToken(token: $token) {
                valid
              }
            }
            ''',
            variables={'token': rotated_refresh},
            token=False,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertNotIn('errors', body)
        self.assertFalse(body['data']['verifyToken']['valid'])

    @override_settings(GRAPHQL_AUTH_THROTTLE_RATES={
        'register': '5/h',
        'token_auth': '1/m',
        'password_reset': '3/h',
        'password_reset_confirm': '5/h',
        'change_password': '5/h',
        'logout': '20/m',
        'verify_token': '30/m',
    })
    def test_auth_mutations_are_throttled(self):
        for _ in range(2):
            response = self.graphql(
                '''
                mutation {
                  tokenAuth(username: "graphql_user", password: "wrong-password") {
                    access
                  }
                }
                ''',
                token=False,
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertIn('errors', body)
        self.assertEqual(body['errors'][0]['message'], 'Too many requests. Please try again later.')

    @override_settings(GRAPHQL_MAX_REQUEST_BYTES=50)
    def test_graphql_request_size_limit(self):
        response = self.graphql(
            '''
            query {
              me {
                id
                username
              }
            }
            '''
        )
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()['errors'][0]['message'], 'GraphQL request body is too large.')

    def test_graphql_alias_limit(self):
        aliased_fields = '\n'.join(f'a{i}: me {{ id }}' for i in range(25))
        response = self.graphql(f'query {{ {aliased_fields} }}')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertIn('errors', body)

    def test_match_mutations_create_join_and_submit_result(self):
        response = self.graphql(
            '''
            mutation {
              createMatch(game: "FIFA_MOBILE", device: "MOBILE", privacy: "PUBLIC", amount: 10) {
                message
                match { id status joiningCode creator { username } }
              }
            }
            '''
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertNotIn('errors', body)
        match_id = int(body['data']['createMatch']['match']['id'])
        joining_code = body['data']['createMatch']['match']['joiningCode']

        opponent_token = str(RefreshToken.for_user(self.opponent).access_token)
        response = self.graphql(
            '''
            mutation Join($joiningCode: String!) {
              joinMatch(joiningCode: $joiningCode) {
                match { id status joiner { username } }
              }
            }
            ''',
            variables={'joiningCode': joining_code},
            token=opponent_token,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertNotIn('errors', body)
        self.assertEqual(body['data']['joinMatch']['match']['status'], 'JOINED')
        self.assertEqual(body['data']['joinMatch']['match']['joiner']['username'], self.opponent.username)

        response = self.graphql(
            '''
            mutation Submit($matchId: ID!) {
              submitMatchResult(matchId: $matchId, submission: "WON") {
                message
              }
            }
            ''',
            variables={'matchId': match_id},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn('errors', response.json())

        response = self.graphql(
            '''
            mutation Submit($matchId: ID!) {
              submitMatchResult(matchId: $matchId, submission: "LOST") {
                status
                winnerId
                match { status winner { username } }
              }
            }
            ''',
            variables={'matchId': match_id},
            token=opponent_token,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertNotIn('errors', body)
        self.assertEqual(body['data']['submitMatchResult']['status'], 'COMPLETED')
        self.assertEqual(body['data']['submitMatchResult']['match']['winner']['username'], self.user.username)

    @override_settings(WALLET_AUTO_PROCESS_WITHDRAWALS=False)
    def test_wallet_payment_queries_and_mutations(self):
        response = self.graphql(
            '''
            mutation {
              createDeposit(amount: "20.00", paymentMethod: "BANK_TRANSFER") {
                orderId
                status
                amount
                pending
                message
              }
            }
            '''
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertNotIn('errors', body)
        order_id = body['data']['createDeposit']['orderId']
        self.assertEqual(body['data']['createDeposit']['status'], 'PENDING')
        self.assertEqual(body['data']['createDeposit']['amount'], '20.00')

        response = self.graphql(
            '''
            query PaymentStatus($orderId: ID!) {
              paymentStatus(orderId: $orderId) {
                orderId
                status
                pending
              }
            }
            ''',
            variables={'orderId': order_id},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertNotIn('errors', body)
        self.assertEqual(body['data']['paymentStatus']['status'], 'PENDING')

        response = self.graphql(
            '''
            mutation {
              createWithdrawal(
                amount: "5.00",
                paymentMethod: "BANK_TRANSFER",
                accountDetails: "Account 123"
              ) {
                withdrawalId
                status
                amount
                message
              }
            }
            '''
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertNotIn('errors', body)
        self.assertEqual(body['data']['createWithdrawal']['status'], 'PENDING')
        self.assertEqual(body['data']['createWithdrawal']['amount'], '5.00')

    def test_message_notification_and_conversation_operations(self):
        response = self.graphql(
            '''
            mutation Send($receiverId: ID!) {
              sendMessage(receiverId: $receiverId, message: "Hello from GraphQL") {
                id
                message
                senderUsername
                receiverUsername
              }
            }
            ''',
            variables={'receiverId': self.opponent.id},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertNotIn('errors', body)
        self.assertEqual(body['data']['sendMessage']['message'], 'Hello from GraphQL')

        opponent_token = str(RefreshToken.for_user(self.opponent).access_token)
        response = self.graphql(
            '''
            query Conversation($userId: ID!) {
              conversation(userId: $userId) {
                message
                isRead
              }
              conversations {
                username
                unreadCount
              }
              unreadNotificationCount
              notifications {
                id
                message
                isRead
              }
            }
            ''',
            variables={'userId': self.user.id},
            token=opponent_token,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertNotIn('errors', body)
        self.assertEqual(body['data']['conversation'][0]['message'], 'Hello from GraphQL')
        self.assertEqual(body['data']['unreadNotificationCount'], 1)
        notification_id = body['data']['notifications'][0]['id']

        response = self.graphql(
            '''
            mutation Mark($notificationId: ID!) {
              markNotificationRead(notificationId: $notificationId) {
                id
                isRead
              }
            }
            ''',
            variables={'notificationId': notification_id},
            token=opponent_token,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertNotIn('errors', body)
        self.assertTrue(body['data']['markNotificationRead']['isRead'])

    def test_dispute_queries_and_resolve_mutation(self):
        dispute = Dispute.objects.create(match=self.match, status='OPEN')
        staff = User.objects.create_user(
            username='graphql_staff',
            email='graphql_staff@test.com',
            password='testpass123',
            is_staff=True,
            is_support_staff=True,
        )
        staff_token = str(RefreshToken.for_user(staff).access_token)

        response = self.graphql(
            '''
            query {
              disputes(status: "OPEN") {
                id
                status
                matchId
                creatorUsername
                joinerUsername
              }
            }
            '''
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertNotIn('errors', body)
        self.assertIn(dispute.id, {int(item['id']) for item in body['data']['disputes']})

        response = self.graphql(
            '''
            mutation Resolve($disputeId: ID!) {
              resolveDispute(disputeId: $disputeId, status: "RESOLVED", resolutionNotes: "Resolved") {
                id
                status
                resolutionNotes
              }
            }
            ''',
            variables={'disputeId': dispute.id},
            token=staff_token,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertNotIn('errors', body)
        self.assertEqual(body['data']['resolveDispute']['status'], 'RESOLVED')
        self.assertEqual(body['data']['resolveDispute']['resolutionNotes'], 'Resolved')


class BaseAPITestCase(APITestCase):
    """Base test case for API tests"""
    
    def setUp(self):
        """Set up test data"""
        self.client = APIClient()
        
        # Create test users
        self.user1 = User.objects.create_user(
            username='user1',
            email='user1@test.com',
            password='testpass123'
        )
        self.user2 = User.objects.create_user(
            username='user2',
            email='user2@test.com',
            password='testpass123'
        )
        self.staff_user = User.objects.create_user(
            username='staff',
            email='staff@test.com',
            password='testpass123',
            is_support_staff=True,
            is_staff=True
        )
        
        # Get tokens
        self.user1_token = str(RefreshToken.for_user(self.user1).access_token)
        self.user2_token = str(RefreshToken.for_user(self.user2).access_token)
        self.staff_token = str(RefreshToken.for_user(self.staff_user).access_token)
        
        # Create test match
        self.match = Match.objects.create(
            creator=self.user1,
            joiner=self.user2,
            game='FIFA_MOBILE',
            device='MOBILE',
            privacy='PUBLIC',
            amount=50,
            status='DISPUTED'
        )
        
        # Create test dispute
        self.dispute = Dispute.objects.create(
            match=self.match,
            status='OPEN'
        )


class DisputeAPITests(BaseAPITestCase):
    """Test Dispute API endpoints"""
    
    def test_list_disputes_regular_user(self):
        """Test regular user can list their own disputes"""
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.user1_token}')
        response = self.client.get('/api/disputes/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['id'], self.dispute.id)
    
    def test_list_disputes_staff(self):
        """Test staff can list all disputes"""
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.staff_token}')
        response = self.client.get('/api/disputes/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data), 1)
    
    def test_list_disputes_with_status_filter(self):
        """Test filtering disputes by status"""
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.staff_token}')
        response = self.client.get('/api/disputes/?status=OPEN')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # All returned disputes should have OPEN status
        for dispute in response.data:
            self.assertEqual(dispute['status'], 'OPEN')
    
    def test_get_dispute_detail(self):
        """Test get dispute detail"""
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.user1_token}')
        response = self.client.get(f'/api/disputes/{self.dispute.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], self.dispute.id)
        self.assertIn('match_id', response.data)
        self.assertIn('match_game', response.data)
    
    def test_get_dispute_detail_unauthorized(self):
        """Test user cannot access dispute for match they're not part of"""
        # Create another user and match
        user3 = User.objects.create_user(
            username='user3',
            email='user3@test.com',
            password='testpass123'
        )
        user3_token = str(RefreshToken.for_user(user3).access_token)
        
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {user3_token}')
        response = self.client.get(f'/api/disputes/{self.dispute.id}/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
    
    def test_resolve_dispute_staff(self):
        """Test staff can resolve dispute"""
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.staff_token}')
        data = {
            'status': 'RESOLVED',
            'resolution_notes': 'Test resolution'
        }
        response = self.client.post(f'/api/disputes/{self.dispute.id}/resolve/', data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.dispute.refresh_from_db()
        self.assertEqual(self.dispute.status, 'RESOLVED')
        self.assertEqual(self.dispute.resolution_notes, 'Test resolution')
        self.assertIsNotNone(self.dispute.resolved_at)
    
    def test_resolve_dispute_regular_user_forbidden(self):
        """Test regular user cannot resolve dispute"""
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.user1_token}')
        data = {'status': 'RESOLVED'}
        response = self.client.post(f'/api/disputes/{self.dispute.id}/resolve/', data)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
    
    def test_list_disputes_unauthenticated(self):
        """Test unauthenticated user cannot list disputes"""
        self.client.credentials()
        response = self.client.get('/api/disputes/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class MessageAPITests(BaseAPITestCase):
    """Test Message API endpoints"""
    
    def test_send_message(self):
        """Test sending a message"""
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.user1_token}')
        data = {
            'receiver': self.user2.id,
            'message': 'Hello!'
        }
        response = self.client.post('/api/messages/', data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Message.objects.count(), 1)
        message = Message.objects.first()
        self.assertEqual(message.sender, self.user1)
        self.assertEqual(message.receiver, self.user2)
        self.assertEqual(message.message, 'Hello!')
    
    def test_send_message_creates_notification(self):
        """Test sending a message creates notification for receiver"""
        initial_count = Notification.objects.count()
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.user1_token}')
        data = {
            'receiver': self.user2.id,
            'message': 'Hello!'
        }
        response = self.client.post('/api/messages/', data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Notification.objects.count(), initial_count + 1)
        notification = Notification.objects.filter(user=self.user2).latest('created_at')
        self.assertIn(self.user1.username, notification.message)
    
    def test_cannot_message_self(self):
        """Test user cannot message themselves"""
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.user1_token}')
        data = {
            'receiver': self.user1.id,
            'message': 'Hello!'
        }
        response = self.client.post('/api/messages/', data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('receiver', response.data)
    
    def test_list_messages(self):
        """Test listing messages"""
        Message.objects.create(
            sender=self.user1,
            receiver=self.user2,
            message='Test message'
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.user1_token}')
        response = self.client.get('/api/messages/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['message'], 'Test message')
    
    def test_list_messages_shows_sent_and_received(self):
        """Test listing messages shows both sent and received"""
        Message.objects.create(
            sender=self.user1,
            receiver=self.user2,
            message='Message 1'
        )
        Message.objects.create(
            sender=self.user2,
            receiver=self.user1,
            message='Message 2'
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.user1_token}')
        response = self.client.get('/api/messages/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)
    
    def test_list_conversations(self):
        """Test listing conversations"""
        Message.objects.create(
            sender=self.user1,
            receiver=self.user2,
            message='Test message'
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.user1_token}')
        response = self.client.get('/api/messages/conversations/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['user_id'], self.user2.id)
        self.assertEqual(response.data[0]['username'], self.user2.username)
        self.assertIn('latest_message', response.data[0])
        self.assertIn('unread_count', response.data[0])
    
    def test_list_conversations_unread_count(self):
        """Test conversations list shows correct unread count"""
        # Create unread message
        Message.objects.create(
            sender=self.user2,
            receiver=self.user1,
            message='Unread message'
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.user1_token}')
        response = self.client.get('/api/messages/conversations/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data[0]['unread_count'], 1)
    
    def test_get_conversation(self):
        """Test getting conversation"""
        Message.objects.create(
            sender=self.user1,
            receiver=self.user2,
            message='Message 1'
        )
        Message.objects.create(
            sender=self.user2,
            receiver=self.user1,
            message='Message 2'
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.user1_token}')
        response = self.client.get(f'/api/messages/conversation/{self.user2.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)
    
    def test_get_conversation_marks_messages_read(self):
        """Test getting conversation marks received messages as read"""
        # Create unread message from user2 to user1
        message = Message.objects.create(
            sender=self.user2,
            receiver=self.user1,
            message='Unread message'
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.user1_token}')
        response = self.client.get(f'/api/messages/conversation/{self.user2.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Check that message is marked as read
        self.assertTrue(ReadMessage.objects.filter(
            message=message,
            receiver=self.user1
        ).exists())
    
    def test_list_messages_unauthenticated(self):
        """Test unauthenticated user cannot list messages"""
        self.client.credentials()
        response = self.client.get('/api/messages/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class NotificationAPITests(BaseAPITestCase):
    """Test Notification API endpoints"""
    
    def setUp(self):
        """Set up test data"""
        super().setUp()
        self.notification = Notification.objects.create(
            user=self.user1,
            message='Test notification'
        )
    
    def test_list_notifications(self):
        """Test listing notifications"""
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.user1_token}')
        response = self.client.get('/api/notifications/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['id'], self.notification.id)
        self.assertEqual(response.data[0]['message'], 'Test notification')
    
    def test_list_notifications_only_own(self):
        """Test user only sees their own notifications"""
        # Create notification for another user
        Notification.objects.create(
            user=self.user2,
            message='Other user notification'
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.user1_token}')
        response = self.client.get('/api/notifications/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should only see own notification
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['user'], self.user1.id)
    
    def test_get_notification_detail(self):
        """Test getting notification detail"""
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.user1_token}')
        response = self.client.get(f'/api/notifications/{self.notification.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], self.notification.id)
        self.assertIn('is_read', response.data)
    
    def test_get_unread_count(self):
        """Test getting unread count"""
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.user1_token}')
        response = self.client.get('/api/notifications/unread-count/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('unread_count', response.data)
        self.assertEqual(response.data['unread_count'], 1)
    
    def test_get_unread_count_after_reading(self):
        """Test unread count decreases after marking as read"""
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.user1_token}')
        # Mark notification as read
        self.client.post(f'/api/notifications/{self.notification.id}/mark-read/')
        # Check unread count
        response = self.client.get('/api/notifications/unread-count/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['unread_count'], 0)
    
    def test_mark_notification_read(self):
        """Test marking notification as read"""
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.user1_token}')
        response = self.client.post(f'/api/notifications/{self.notification.id}/mark-read/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('message', response.data)
        # Check that ReadNotification was created
        self.assertTrue(ReadNotification.objects.filter(
            notification=self.notification,
            user=self.user1
        ).exists())
    
    def test_mark_notification_read_updates_is_read(self):
        """Test marking notification as read updates is_read field in response"""
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.user1_token}')
        # Get notification before marking as read
        response = self.client.get(f'/api/notifications/{self.notification.id}/')
        self.assertFalse(response.data['is_read'])
        # Mark as read
        self.client.post(f'/api/notifications/{self.notification.id}/mark-read/')
        # Get notification after marking as read
        response = self.client.get(f'/api/notifications/{self.notification.id}/')
        self.assertTrue(response.data['is_read'])
    
    def test_mark_all_read(self):
        """Test marking all notifications as read"""
        # Create multiple notifications
        Notification.objects.create(
            user=self.user1,
            message='Notification 2'
        )
        Notification.objects.create(
            user=self.user1,
            message='Notification 3'
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.user1_token}')
        response = self.client.post('/api/notifications/mark-all-read/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Check unread count is now 0
        response = self.client.get('/api/notifications/unread-count/')
        self.assertEqual(response.data['unread_count'], 0)
    
    def test_cannot_mark_other_user_notification_read(self):
        """Test user cannot mark another user's notification as read"""
        # Create notification for user2
        notification2 = Notification.objects.create(
            user=self.user2,
            message='User2 notification'
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.user1_token}')
        response = self.client.post(f'/api/notifications/{notification2.id}/mark-read/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
    
    def test_list_notifications_unauthenticated(self):
        """Test unauthenticated user cannot list notifications"""
        self.client.credentials()
        response = self.client.get('/api/notifications/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
