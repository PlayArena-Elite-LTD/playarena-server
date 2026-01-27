from django.test import TestCase, Client, override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth import get_user_model
from django.urls import reverse

from matches.models import Match, Evidence
from panel.models import Dispute

User = get_user_model()


@override_settings(
    CACHES={
        'default': {
            'BACKEND': 'django.core.cache.backends.dummy.DummyCache',
        }
    }
)
class DisputeEvidenceDisplayTests(TestCase):
    """Tests for evidence display in dispute detail view."""

    def setUp(self):
        self.client = Client()

        # Create support staff user (can access panel views)
        self.support_staff = User.objects.create_user(
            username='support',
            email='support@example.com',
            password='testpass123',
            is_support_staff=True
        )

        # Creator and joiner
        self.creator = User.objects.create_user(
            username='creator',
            email='creator@example.com',
            password='testpass123',
        )
        self.joiner = User.objects.create_user(
            username='joiner',
            email='joiner@example.com',
            password='testpass123',
        )

        # Match and dispute
        self.match = Match.objects.create(
            creator=self.creator,
            joiner=self.joiner,
            game='FIFA_MOBILE',
            device='MOBILE',
            privacy='PUBLIC',
            amount=50,
            status='DISPUTED',
        )

        self.dispute = Dispute.objects.create(
            match=self.match,
            status='OPEN',
        )

        # Evidence from creator
        creator_file = SimpleUploadedFile(
            "creator_image.jpg",
            b"fake image content",
            content_type="image/jpeg"
        )
        self.creator_evidence = Evidence.objects.create(
            match=self.match,
            user=self.creator,
            file=creator_file,
            file_type='IMAGE',
            file_size=len(b"fake image content"),
            ip_address='127.0.0.1'
        )

        # Evidence from joiner
        joiner_file = SimpleUploadedFile(
            "joiner_image.jpg",
            b"fake image content",
            content_type="image/jpeg"
        )
        self.joiner_evidence = Evidence.objects.create(
            match=self.match,
            user=self.joiner,
            file=joiner_file,
            file_type='IMAGE',
            file_size=len(b"fake image content"),
            ip_address='127.0.0.1'
        )

    def test_dispute_detail_shows_evidence_sections(self):
        """Ensure dispute detail view shows evidence for both participants."""
        self.client.login(username='support', password='testpass123')
        url = reverse('dispute_detail', args=[self.dispute.id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)

        content = response.content.decode('utf-8')
        # Check creator section and evidence
        self.assertIn('Evidence from {}'.format(self.creator.username), content)
        self.assertIn('creator_image.jpg', content)

        # Check joiner section and evidence
        self.assertIn('Evidence from {}'.format(self.joiner.username), content)
        self.assertIn('joiner_image.jpg', content)

        # Check links use the secure endpoints
        self.assertIn(reverse('get_evidence', args=[self.creator_evidence.id]), content)
        self.assertIn(reverse('download_evidence', args=[self.creator_evidence.id]), content)

    def test_dispute_detail_no_evidence_message(self):
        """Ensure a helpful message is shown when no evidence exists."""
        # Remove existing evidence
        Evidence.objects.all().delete()

        self.client.login(username='support', password='testpass123')
        url = reverse('dispute_detail', args=[self.dispute.id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        self.assertIn('No evidence has been submitted for this match yet.', content)
