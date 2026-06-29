import json
from decimal import Decimal
from requests import HTTPError
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from rest_framework import status
from rest_framework.test import APITestCase, APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from alert.models import Notification, ReadNotification
from matches.models import Match
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


class LipilaGatewayVerifyTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='payer',
            email='payer@test.com',
            password='pass1234',
        )
        self.wallet, _ = Wallet.objects.get_or_create(user=self.user)

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
