from django.core import mail
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Organisation


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


class OrganisationAuthApiTests(APITestCase):
    def registration_payload(self, **overrides):
        payload = {
            'organisation_name': 'Lusaka Esports Hub',
            'contact_name': 'Martha Banda',
            'email': 'organiser@example.com',
            'phone': '+260971234567',
            'organisation_type': Organisation.OrganisationType.TOURNAMENT_ORGANISER,
            'city': 'Lusaka',
            'password': 'OrganiserPass123!',
            'password_confirm': 'OrganiserPass123!',
        }
        payload.update(overrides)
        return payload

    def test_organisation_registration_creates_owner_and_returns_tokens(self):
        response = self.client.post(
            reverse('api_organisation_register'),
            self.registration_payload(),
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('access', response.data)
        self.assertIn('refresh', response.data)
        self.assertEqual(response.data['organisation']['name'], 'Lusaka Esports Hub')
        self.assertEqual(response.data['organisation']['email'], 'organiser@example.com')
        self.assertTrue(get_user_model().objects.filter(email='organiser@example.com').exists())
        self.assertTrue(Organisation.objects.filter(email='organiser@example.com').exists())

    def test_organisation_login_returns_organisation_and_tokens(self):
        self.client.post(
            reverse('api_organisation_register'),
            self.registration_payload(),
            format='json',
        )

        response = self.client.post(
            reverse('api_organisation_login'),
            {
                'email': 'organiser@example.com',
                'password': 'OrganiserPass123!',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)
        self.assertEqual(response.data['organisation']['name'], 'Lusaka Esports Hub')

    def test_organisation_me_returns_authenticated_owner_organisation(self):
        registration = self.client.post(
            reverse('api_organisation_register'),
            self.registration_payload(),
            format='json',
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {registration.data['access']}")

        response = self.client.get(reverse('api_organisation_me'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['email'], 'organiser@example.com')

    def test_organisation_registration_rejects_duplicate_email(self):
        self.client.post(
            reverse('api_organisation_register'),
            self.registration_payload(),
            format='json',
        )

        response = self.client.post(
            reverse('api_organisation_register'),
            self.registration_payload(organisation_name='Duplicate Org'),
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('email', response.data)
