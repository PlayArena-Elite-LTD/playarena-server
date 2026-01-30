from decimal import Decimal

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import CustomUser
from wallet.models import Wallet, Transaction, Deposit, Withdrawal


class WalletApiTests(APITestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='walletuser',
            email='walletuser@example.com',
            password='Pass12345!'
        )
        self.client.force_authenticate(user=self.user)

    def test_wallet_detail_requires_auth(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(reverse('api_wallet'))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_wallet_detail_returns_balance(self):
        wallet = Wallet.objects.get(user=self.user)
        wallet.balance = Decimal('50.00')
        wallet.save(update_fields=['balance'])

        response = self.client.get(reverse('api_wallet'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], wallet.id)
        self.assertEqual(Decimal(response.data['balance']), wallet.balance)

    def test_transaction_history_returns_user_transactions(self):
        wallet = Wallet.objects.get(user=self.user)
        Transaction.objects.create(
            wallet=wallet,
            amount=Decimal('10.00'),
            transaction_type='DEPOSIT',
            description='Initial deposit'
        )
        Transaction.objects.create(
            wallet=wallet,
            amount=Decimal('-5.00'),
            transaction_type='WITHDRAWAL',
            description='Test withdrawal'
        )

        response = self.client.get(reverse('api_wallet_transactions'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)
        self.assertEqual(response.data[0]['description'], 'Test withdrawal')

    def test_create_deposit(self):
        response = self.client.post(
            reverse('api_wallet_deposit'),
            {'amount': '25.00', 'payment_method': 'PAYPAL'},
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(
            Deposit.objects.filter(
                user=self.user,
                amount=Decimal('25.00'),
                payment_method='PAYPAL',
                status='PENDING'
            ).exists()
        )

    def test_create_withdrawal_requires_balance(self):
        wallet = Wallet.objects.get(user=self.user)
        wallet.balance = Decimal('100.00')
        wallet.save(update_fields=['balance'])
        self.user.refresh_from_db()
        self.client.force_authenticate(user=self.user)

        response = self.client.post(
            reverse('api_wallet_withdraw'),
            {
                'amount': '40.00',
                'payment_method': 'BANK_TRANSFER',
                'account_details': '1234567890|001'
            },
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(
            Withdrawal.objects.filter(
                user=self.user,
                amount=Decimal('40.00'),
                payment_method='BANK_TRANSFER',
                status='PENDING'
            ).exists()
        )
