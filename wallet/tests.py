from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from wallet.models import Transaction, Wallet, Withdrawal


class WithdrawalViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='withdrawer',
            email='withdrawer@test.com',
            password='pass1234',
        )
        self.wallet, _ = Wallet.objects.get_or_create(user=self.user)
        self.wallet.balance = Decimal('10.00')
        self.wallet.save(update_fields=['balance'])
        self.client.force_login(self.user)

    def test_withdraw_full_balance_creates_pending_withdrawal(self):
        response = self.client.post(reverse('withdraw'), {
            'amount': '10.00',
            'payment_method': 'MOBILE_MONEY',
            'account_details': '260974221154|Airtel',
        })

        self.assertRedirects(response, reverse('wallet'))

        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal('0.00'))

        withdrawal = Withdrawal.objects.get(user=self.user)
        self.assertEqual(withdrawal.status, 'PENDING')
        self.assertEqual(withdrawal.amount, Decimal('10.00'))
        self.assertEqual(withdrawal.payment_method, 'MOBILE_MONEY')
        self.assertEqual(withdrawal.account_details, '260974221154|Airtel')

        transaction = Transaction.objects.get(wallet=self.wallet, transaction_type='WITHDRAWAL')
        self.assertEqual(transaction.amount, Decimal('-10.00'))

    def test_withdraw_screen_renders(self):
        response = self.client.get(reverse('withdraw'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Withdraw Funds')
        self.assertContains(response, 'Available Balance')
