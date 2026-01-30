from decimal import Decimal

from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from django.core.management import call_command

from wallet.models import Wallet, Transaction


User = get_user_model()


@override_settings(
    CACHES={
        'default': {
            'BACKEND': 'django.core.cache.backends.dummy.DummyCache',
        }
    }
)
class WalletReconciliationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='recon_user',
            email='recon_user@example.com',
            password='testpass123',
        )
        self.wallet = self.user.wallet

    def test_verify_balance_integrity_valid(self):
        """Wallet should be valid when balance matches transaction sum."""
        Transaction.objects.create(
            wallet=self.wallet,
            amount=Decimal('100.00'),
            transaction_type='DEPOSIT',
            description='Test deposit',
        )
        self.wallet.balance = Decimal('100.00')
        self.wallet.save(update_fields=['balance'])

        result = self.wallet.verify_balance_integrity()
        self.assertTrue(result['is_valid'])
        self.assertEqual(result['expected_balance'], Decimal('100.00'))
        self.assertEqual(result['actual_balance'], Decimal('100.00'))

    def test_verify_balance_integrity_invalid(self):
        """Wallet should be invalid when balance does not match transaction sum."""
        Transaction.objects.create(
            wallet=self.wallet,
            amount=Decimal('50.00'),
            transaction_type='DEPOSIT',
            description='Test deposit',
        )
        self.wallet.balance = Decimal('75.00')
        self.wallet.save(update_fields=['balance'])

        result = self.wallet.verify_balance_integrity()
        self.assertFalse(result['is_valid'])
        self.assertEqual(result['expected_balance'], Decimal('50.00'))
        self.assertEqual(result['actual_balance'], Decimal('75.00'))
        self.assertEqual(result['discrepancy'], Decimal('25.00'))

    def test_recalculate_balance_fixes_discrepancy(self):
        """recalculate_balance should update balance to match transaction sum."""
        Transaction.objects.create(
            wallet=self.wallet,
            amount=Decimal('40.00'),
            transaction_type='DEPOSIT',
            description='Test deposit',
        )
        self.wallet.balance = Decimal('10.00')
        self.wallet.save(update_fields=['balance'])

        new_balance = self.wallet.recalculate_balance()
        self.wallet.refresh_from_db()
        self.assertEqual(new_balance, Decimal('40.00'))
        self.assertEqual(self.wallet.balance, Decimal('40.00'))

    def test_reconcile_command_dry_run(self):
        """reconcile_wallets --dry-run should not change wallet balances."""
        Transaction.objects.create(
            wallet=self.wallet,
            amount=Decimal('30.00'),
            transaction_type='DEPOSIT',
            description='Test deposit',
        )
        self.wallet.balance = Decimal('0.00')
        self.wallet.save(update_fields=['balance'])

        call_command('reconcile_wallets', '--dry-run')
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal('0.00'))

    def test_reconcile_command_fix(self):
        """reconcile_wallets without dry-run should fix balances."""
        Transaction.objects.create(
            wallet=self.wallet,
            amount=Decimal('30.00'),
            transaction_type='DEPOSIT',
            description='Test deposit',
        )
        self.wallet.balance = Decimal('0.00')
        self.wallet.save(update_fields=['balance'])

        call_command('reconcile_wallets')
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal('30.00'))
