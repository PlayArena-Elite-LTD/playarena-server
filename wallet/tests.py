from decimal import Decimal
from unittest.mock import Mock, patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from wallet.admin import WithdrawalAdmin
from wallet.models import Transaction, Wallet, Withdrawal
from wallet.utils import process_withdrawal_and_debit_wallet
from wallet.withdrawal_processing import apply_lipila_withdrawal_webhook


@override_settings(
    RATELIMIT_ENABLE=False,
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
)
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
        self.assertEqual(self.wallet.balance, Decimal('10.00'))

        withdrawal = Withdrawal.objects.get(user=self.user)
        self.assertEqual(withdrawal.status, 'PENDING')
        self.assertEqual(withdrawal.amount, Decimal('10.00'))
        self.assertEqual(withdrawal.payment_method, 'MOBILE_MONEY')
        self.assertEqual(withdrawal.account_details, '260974221154|Airtel')

        self.assertFalse(
            Transaction.objects.filter(wallet=self.wallet, transaction_type='WITHDRAWAL').exists()
        )
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(mail.outbox[0].to, ['withdrawer@test.com'])
        self.assertIn('Withdrawal request received', mail.outbox[0].subject)
        self.assertEqual(mail.outbox[1].to, ['josephmbuzi9@gmail.com'])
        self.assertIn(f'New withdrawal request #{withdrawal.id}', mail.outbox[1].subject)
        self.assertIn('Account details: 260974221154|Airtel', mail.outbox[1].body)

    def test_withdraw_screen_renders(self):
        response = self.client.get(reverse('withdraw'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Withdraw Funds')
        self.assertContains(response, 'Available Balance')

    @override_settings(WALLET_AUTO_PROCESS_WITHDRAWALS=True)
    @patch('wallet.withdrawal_processing.get_payment_manager')
    def test_mobile_money_withdrawal_auto_processes_to_lipila_pending(self, get_payment_manager):
        manager = Mock()
        manager.process_withdrawal.return_value = {
            'success': True,
            'transaction_id': 'LPLXC-20260625-0001',
            'gateway_response': {
                'reference_id': 'WDR_1_1782389900',
                'referenceId': 'WDR_1_1782389900',
                'identifier': 'LPLXC-20260625-0001',
                'status': 'Pending',
            },
            'failure_reason': None,
        }
        get_payment_manager.return_value = manager

        response = self.client.post(reverse('withdraw'), {
            'amount': '10.00',
            'payment_method': 'MOBILE_MONEY',
            'account_details': '260974221154|Airtel',
        })

        self.assertRedirects(response, reverse('wallet'))
        withdrawal = Withdrawal.objects.get(user=self.user)
        self.assertEqual(withdrawal.status, 'PROCESSING')
        self.assertEqual(withdrawal.gateway_transaction_id, 'LPLXC-20260625-0001')
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal('10.00'))

    def test_lipila_failed_withdrawal_webhook_does_not_change_pending_balance(self):
        self.client.post(reverse('withdraw'), {
            'amount': '10.00',
            'payment_method': 'MOBILE_MONEY',
            'account_details': '260974221154|Airtel',
        })
        withdrawal = Withdrawal.objects.get(user=self.user)
        Withdrawal.objects.filter(id=withdrawal.id).update(
            status='PROCESSING',
            transaction_id='LPLXC-20260625-0001',
            gateway_transaction_id='LPLXC-20260625-0001',
            gateway_response={'reference_id': 'WDR_1_1782389900'},
        )

        result = apply_lipila_withdrawal_webhook({
            'referenceId': 'WDR_1_1782389900',
            'identifier': 'LPLXC-20260625-0001',
            'status': 'Failed',
            'message': 'Transaction is not found',
        })

        self.assertTrue(result['processed'])
        withdrawal.refresh_from_db()
        self.wallet.refresh_from_db()
        self.assertEqual(withdrawal.status, 'FAILED')
        self.assertEqual(self.wallet.balance, Decimal('10.00'))
        self.assertFalse(
            Transaction.objects.filter(
                wallet=self.wallet,
                transaction_type='OTHER',
                amount=Decimal('10.00'),
            ).exists()
        )

    def test_lipila_successful_withdrawal_webhook_debits_balance_once(self):
        self.client.post(reverse('withdraw'), {
            'amount': '10.00',
            'payment_method': 'MOBILE_MONEY',
            'account_details': '260974221154|Airtel',
        })
        withdrawal = Withdrawal.objects.get(user=self.user)
        Withdrawal.objects.filter(id=withdrawal.id).update(
            status='PROCESSING',
            transaction_id='LPLXC-20260625-0001',
            gateway_transaction_id='LPLXC-20260625-0001',
            gateway_response={'reference_id': 'WDR_1_1782389900'},
        )

        result = apply_lipila_withdrawal_webhook({
            'referenceId': 'WDR_1_1782389900',
            'identifier': 'LPLXC-20260625-0001',
            'status': 'Successful',
            'message': 'Successful',
        })

        self.assertTrue(result['processed'])
        withdrawal.refresh_from_db()
        self.wallet.refresh_from_db()
        self.assertEqual(withdrawal.status, 'COMPLETED')
        self.assertEqual(self.wallet.balance, Decimal('0.00'))
        self.assertEqual(
            Transaction.objects.filter(
                wallet=self.wallet,
                transaction_type='WITHDRAWAL',
                amount=Decimal('-10.00'),
            ).count(),
            1,
        )

    @override_settings(WALLET_AUTO_PROCESS_WITHDRAWALS=True)
    @patch('wallet.withdrawal_processing.get_payment_manager')
    def test_lipila_timeout_keeps_withdrawal_processing_with_reference(self, get_payment_manager):
        manager = Mock()
        manager.process_withdrawal.return_value = {
            'success': False,
            'transaction_id': 'WDR_1',
            'gateway_response': {
                'status': 'unknown_timeout',
                'reference_id': 'WDR_1',
                'referenceId': 'WDR_1',
                'gateway': 'lipila',
            },
            'failure_reason': 'Lipila request timed out after submission; awaiting callback or manual verification.',
        }
        get_payment_manager.return_value = manager

        response = self.client.post(reverse('withdraw'), {
            'amount': '10.00',
            'payment_method': 'MOBILE_MONEY',
            'account_details': '260974221154|Airtel',
        })

        self.assertRedirects(response, reverse('wallet'))
        withdrawal = Withdrawal.objects.get(user=self.user)
        self.assertEqual(withdrawal.status, 'PROCESSING')
        self.assertEqual(withdrawal.transaction_id, 'WDR_1')
        self.assertEqual(withdrawal.retry_count, 0)
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal('10.00'))


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


@override_settings(
    RATELIMIT_ENABLE=False,
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
)
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

    def test_admin_completion_debits_withdrawal_once(self):
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

    def test_admin_completion_does_not_debit_legacy_reserved_withdrawal_again(self):
        withdrawal = Withdrawal.objects.get(user=self.user)
        process_withdrawal_and_debit_wallet(withdrawal)
        Withdrawal.objects.filter(id=withdrawal.id).update(status='PENDING')
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal('0.00'))

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

    def test_admin_failure_does_not_change_pending_balance(self):
        withdrawal = Withdrawal.objects.get(user=self.user)

        self.admin.mark_as_failed(
            self.request,
            Withdrawal.objects.filter(id=withdrawal.id),
        )

        self.wallet.refresh_from_db()
        withdrawal.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal('10.00'))
        self.assertEqual(withdrawal.status, 'FAILED')
        self.assertFalse(
            Transaction.objects.filter(
                wallet=self.wallet,
                transaction_type='OTHER',
                amount=Decimal('10.00'),
                description__startswith=f'Withdrawal {withdrawal.id} refund',
            ).exists()
        )
