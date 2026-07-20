from django.core import mail
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class PasswordResetViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='reset-user',
            email='reset@example.com',
            password='pass1234',
        )

    def test_password_reset_post_uses_request_for_rate_limit(self):
        response = self.client.post(
            reverse('password_reset'),
            {'email': 'missing@example.com'},
        )

        self.assertRedirects(response, reverse('password_reset_done'))
        self.assertEqual(len(mail.outbox), 0)

    def test_password_reset_sends_email_for_existing_active_user(self):
        response = self.client.post(
            reverse('password_reset'),
            {'email': self.user.email},
        )

        self.assertRedirects(response, reverse('password_reset_done'))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.user.email])
        self.assertIn('/accounts/reset/', mail.outbox[0].body)
