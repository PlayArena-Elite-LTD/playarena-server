from decimal import Decimal

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.urls import reverse

from wallet.admin import WithdrawalAdmin
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


class TransactionHistoryViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='transaction-user',
            email='transaction-user@test.com',
            password='pass1234',
        )
        self.wallet, _ = Wallet.objects.get_or_create(user=self.user)
        self.wallet.balance = Decimal('25.50')
        self.wallet.save(update_fields=['balance'])
        self.client.force_login(self.user)

    def test_transaction_history_shows_available_balance(self):
        response = self.client.get(reverse('transaction_history'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Available Balance')
        self.assertContains(response, '$25.50')


class WithdrawalAdminTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username='withdrawer',
            email='withdrawer@test.com',
            password='pass1234',
        )
        self.staff = User.objects.create_superuser(
            username='admin',
            email='admin@test.com',
            password='pass1234',
        )
        self.wallet, _ = Wallet.objects.get_or_create(user=self.user)
        self.wallet.balance = Decimal('10.00')
        self.wallet.save(update_fields=['balance'])
        self.client.force_login(self.user)
        self.client.post(reverse('withdraw'), {
            'amount': '10.00',
            'payment_method': 'MOBILE_MONEY',
            'account_details': '260974221154|Airtel',
        })

        self.request = RequestFactory().post('/admin/wallet/withdrawal/')
        self.request.user = self.staff
        self.admin = WithdrawalAdmin(Withdrawal, admin.site)
        self.admin.message_user = lambda *args, **kwargs: None

    def test_admin_completion_does_not_debit_reserved_withdrawal_again(self):
        withdrawal = Withdrawal.objects.get(user=self.user)

        self.admin.mark_as_completed(
            self.request,
            Withdrawal.objects.filter(id=withdrawal.id),
        )

        self.wallet.refresh_from_db()
        withdrawal.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal('0.00'))
        self.assertEqual(withdrawal.status, 'COMPLETED')
        self.assertEqual(
            Transaction.objects.filter(
                wallet=self.wallet,
                transaction_type='WITHDRAWAL',
                amount=Decimal('-10.00'),
            ).count(),
            1,
        )

    def test_admin_failure_refunds_reserved_withdrawal(self):
        withdrawal = Withdrawal.objects.get(user=self.user)

        self.admin.mark_as_failed(
            self.request,
            Withdrawal.objects.filter(id=withdrawal.id),
        )

        self.wallet.refresh_from_db()
        withdrawal.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal('10.00'))
        self.assertEqual(withdrawal.status, 'FAILED')
        self.assertTrue(
            Transaction.objects.filter(
                wallet=self.wallet,
                transaction_type='OTHER',
                amount=Decimal('10.00'),
                description__startswith=f'Withdrawal {withdrawal.id} refund',
            ).exists()
        )
