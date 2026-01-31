from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
from matches.models import Match
from panel.models import Dispute
from messenger.models import Message, ReadMessage
from alert.models import Notification, ReadNotification

User = get_user_model()


class APITestCase(TestCase):
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


class DisputeAPITests(APITestCase):
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


class MessageAPITests(APITestCase):
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


class NotificationAPITests(APITestCase):
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
