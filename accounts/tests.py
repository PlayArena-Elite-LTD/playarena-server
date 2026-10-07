from decimal import Decimal

from django.core import mail
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Organisation
from wallet.models import OrganisationWallet
from wallet.models import OrganisationTransaction, Transaction, Wallet, Deposit, Withdrawal
from wallet.payment_processing import apply_deposit_webhook_status
from wallet.utils import process_withdrawal_and_debit_wallet, refund_withdrawal_reservation


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

    def test_organisation_has_wallet_created_automatically(self):
        registration = self.client.post(
            reverse('api_organisation_register'),
            self.registration_payload(),
            format='json',
        )

        self.assertEqual(registration.status_code, status.HTTP_201_CREATED)
        organisation = Organisation.objects.get(email='organiser@example.com')
        wallet = organisation.wallet
        self.assertIsInstance(wallet, OrganisationWallet)
        self.assertEqual(wallet.balance, 0)

    def test_organisation_owner_can_access_wallet_endpoint(self):
        registration = self.client.post(
            reverse('api_organisation_register'),
            self.registration_payload(),
            format='json',
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {registration.data['access']}")

        response = self.client.get('/api/organisations/wallet/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['balance'], '0.00')

    def test_organisation_deposit_is_credited_to_organisation_wallet_only(self):
        registration = self.client.post(
            reverse('api_organisation_register'),
            self.registration_payload(),
            format='json',
        )
        owner = get_user_model().objects.get(email='organiser@example.com')
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {registration.data['access']}")

        response = self.client.post(
            reverse('api_organisation_wallet_deposit'),
            {'amount': '25.00', 'payment_method': 'OTHER'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        deposit = Deposit.objects.get(id=response.data['deposit_id'])
        self.assertIsNone(deposit.wallet_id)
        self.assertEqual(deposit.organisation_wallet.organisation.owner, owner)
        self.assertEqual(owner.wallet.balance, 0)

        apply_deposit_webhook_status(deposit, payment_status='Successful')
        apply_deposit_webhook_status(deposit, payment_status='Successful')
        deposit.organisation_wallet.refresh_from_db()
        owner.wallet.refresh_from_db()
        self.assertEqual(deposit.organisation_wallet.balance, Decimal('25.00'))
        self.assertEqual(owner.wallet.balance, Decimal('0.00'))
        self.assertEqual(
            OrganisationTransaction.objects.filter(
                wallet=deposit.organisation_wallet,
                transaction_type='DEPOSIT',
                amount=Decimal('25.00'),
            ).count(),
            1,
        )
        self.assertFalse(Transaction.objects.filter(wallet=owner.wallet, transaction_type='DEPOSIT').exists())

    def test_organisation_withdrawal_debits_only_organisation_wallet(self):
        registration = self.client.post(
            reverse('api_organisation_register'),
            self.registration_payload(),
            format='json',
        )
        owner = get_user_model().objects.get(email='organiser@example.com')
        organisation = Organisation.objects.get(owner=owner)
        organisation_wallet = organisation.wallet
        organisation_wallet.balance = Decimal('80.00')
        organisation_wallet.save(update_fields=['balance'])
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {registration.data['access']}")

        response = self.client.post(
            reverse('api_organisation_wallet_withdraw'),
            {
                'amount': '30.00',
                'payment_method': 'BANK_TRANSFER',
                'account_details': 'Example Bank | 12345678',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        withdrawal = Withdrawal.objects.get(id=response.data['withdrawal_id'])
        organisation_wallet.refresh_from_db()
        owner.wallet.refresh_from_db()
        self.assertEqual(withdrawal.organisation_wallet, organisation_wallet)
        self.assertIsNone(withdrawal.wallet_id)
        self.assertEqual(organisation_wallet.balance, Decimal('50.00'))
        self.assertEqual(owner.wallet.balance, Decimal('0.00'))
        self.assertTrue(
            OrganisationTransaction.objects.filter(
                wallet=organisation_wallet,
                amount=Decimal('-30.00'),
                transaction_type='WITHDRAWAL',
            ).exists()
        )
        self.assertFalse(Transaction.objects.filter(wallet=owner.wallet, transaction_type='WITHDRAWAL').exists())

        completion = process_withdrawal_and_debit_wallet(withdrawal)
        self.assertTrue(completion['success'])
        withdrawal.refresh_from_db()
        organisation_wallet.refresh_from_db()
        self.assertEqual(withdrawal.status, 'COMPLETED')
        self.assertEqual(organisation_wallet.balance, Decimal('50.00'))
        self.assertEqual(
            OrganisationTransaction.objects.filter(
                wallet=organisation_wallet,
                transaction_type='WITHDRAWAL',
                amount=Decimal('-30.00'),
            ).count(),
            1,
        )

        failed_response = self.client.post(
            reverse('api_organisation_wallet_withdraw'),
            {
                'amount': '10.00',
                'payment_method': 'BANK_TRANSFER',
                'account_details': 'Example Bank | 12345678',
            },
            format='json',
        )
        self.assertEqual(failed_response.status_code, status.HTTP_201_CREATED)
        failed_withdrawal = Withdrawal.objects.get(id=failed_response.data['withdrawal_id'])
        Withdrawal.objects.filter(id=failed_withdrawal.id).update(status='FAILED')
        refund = refund_withdrawal_reservation(failed_withdrawal, 'Test failure')
        organisation_wallet.refresh_from_db()
        self.assertTrue(refund['refunded'])
        self.assertEqual(organisation_wallet.balance, Decimal('50.00'))
        self.assertTrue(
            OrganisationTransaction.objects.filter(
                wallet=organisation_wallet,
                transaction_type='OTHER',
                amount=Decimal('10.00'),
                description__startswith=f'Withdrawal {failed_withdrawal.id} refund',
            ).exists()
        )
        self.assertEqual(
            self.client.get(reverse('api_organisation_wallet_withdrawals')).data[0]['id'],
            failed_withdrawal.id,
        )
