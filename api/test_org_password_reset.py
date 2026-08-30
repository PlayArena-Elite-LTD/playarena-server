"""Tests for organiser password reset (request + confirm)."""
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from rest_framework.test import APITestCase, APIClient

from accounts.models import Organisation

User = get_user_model()

REQ = '/api/auth/organisations/password-reset/'
CONFIRM = '/api/auth/organisations/password-reset/confirm/'


class OrgPasswordResetTests(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = User.objects.create_user('org-owner', 'owner@org.com', 'oldpass123')
        self.org = Organisation.objects.create(
            owner=self.owner, name='Lusaka Hub', contact_name='M B',
            email='hub@org.com', phone='+260971234567',
            organisation_type=Organisation.OrganisationType.TOURNAMENT_ORGANISER,
            city='Lusaka',
        )
        self.player = User.objects.create_user('player', 'player@t.com', 'oldpass123')

    def _uid_token(self, user):
        return urlsafe_base64_encode(force_bytes(user.pk)), default_token_generator.make_token(user)

    # ---- request ----
    def test_request_emails_organiser_owner(self):
        res = self.client.post(REQ, {'email': 'owner@org.com'}, format='json')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('reset-password', mail.outbox[0].body)
        self.assertIn('uid=', mail.outbox[0].body)
        self.assertEqual(mail.outbox[0].to, ['owner@org.com'])

    def test_request_matches_organisation_contact_email(self):
        # Owner logs in with owner@org.com but the organisation's own email is
        # different; requesting a reset with the ORG email must also work.
        self.org.email = 'contact@org.com'
        self.org.save(update_fields=['email'])
        res = self.client.post(REQ, {'email': 'contact@org.com'}, format='json')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['owner@org.com'])  # sent to login email

    def test_request_case_insensitive_email(self):
        res = self.client.post(REQ, {'email': 'OWNER@ORG.com'}, format='json')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)

    def test_request_for_player_sends_nothing_but_is_neutral(self):
        res = self.client.post(REQ, {'email': 'player@t.com'}, format='json')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)  # not an organiser -> no email

    def test_request_for_unknown_email_is_neutral(self):
        res = self.client.post(REQ, {'email': 'nobody@nowhere.com'}, format='json')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)

    def test_request_requires_email(self):
        res = self.client.post(REQ, {}, format='json')
        self.assertEqual(res.status_code, 400)

    # ---- confirm ----
    def test_confirm_sets_new_password(self):
        uid, token = self._uid_token(self.owner)
        res = self.client.post(CONFIRM, {
            'uid': uid, 'token': token,
            'new_password': 'BrandNewPass!234', 'new_password_confirm': 'BrandNewPass!234',
        }, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.check_password('BrandNewPass!234'))

    def test_confirm_rejects_bad_token(self):
        uid, _ = self._uid_token(self.owner)
        res = self.client.post(CONFIRM, {
            'uid': uid, 'token': 'not-a-real-token',
            'new_password': 'BrandNewPass!234', 'new_password_confirm': 'BrandNewPass!234',
        }, format='json')
        self.assertEqual(res.status_code, 400)
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.check_password('oldpass123'))  # unchanged

    def test_confirm_rejects_non_organiser(self):
        uid, token = self._uid_token(self.player)
        res = self.client.post(CONFIRM, {
            'uid': uid, 'token': token,
            'new_password': 'BrandNewPass!234', 'new_password_confirm': 'BrandNewPass!234',
        }, format='json')
        self.assertEqual(res.status_code, 400)

    def test_confirm_rejects_password_mismatch(self):
        uid, token = self._uid_token(self.owner)
        res = self.client.post(CONFIRM, {
            'uid': uid, 'token': token,
            'new_password': 'BrandNewPass!234', 'new_password_confirm': 'different!234',
        }, format='json')
        self.assertEqual(res.status_code, 400)

    def test_token_is_single_use(self):
        uid, token = self._uid_token(self.owner)
        first = self.client.post(CONFIRM, {
            'uid': uid, 'token': token,
            'new_password': 'BrandNewPass!234', 'new_password_confirm': 'BrandNewPass!234',
        }, format='json')
        self.assertEqual(first.status_code, 200)
        # reusing the same token after the password changed must fail
        second = self.client.post(CONFIRM, {
            'uid': uid, 'token': token,
            'new_password': 'AnotherPass!234', 'new_password_confirm': 'AnotherPass!234',
        }, format='json')
        self.assertEqual(second.status_code, 400)
