import json
from decimal import Decimal
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from services.payments.factory import get_active_payment_provider, get_payment_gateway
from services.payments.zynle_gateway import ZynleGateway
from services.payments.zynle_service import ZynleService
from wallet.models import Deposit, PaymentGatewaySetting, Transaction, Wallet


class ZynleServiceTests(TestCase):
    @patch('services.payments.zynle_service.requests.post')
    def test_momo_deposit_sends_configured_json_fields(self, post):
        response = Mock()
        response.json.return_value = {'response_code': 120, 'transaction_id': 'TX1'}
        post.return_value = response
        service = ZynleService(
            base_url='https://sandbox.example/jsonapi',
            api_key='key',
            api_id='id',
            merchant_id='merchant',
        )

        service.momo_deposit(
            sender_id='260971234567', amount=Decimal('25.50'), reference_no='DEP_1'
        )

        payload = post.call_args.kwargs['json']
        self.assertEqual(payload, {
            'auth': {
                'merchant_id': 'merchant',
                'api_id': 'id',
                'api_key': 'key',
                'channel': 'momo',
            },
            'data': {
                'method': 'runBillPayment',
                'sender_id': '260971234567',
                'reference_no': 'DEP_1',
                'amount': '25.50',
            },
        })
        self.assertEqual(post.call_args.kwargs['headers']['Accept'], '*/*')

    @patch('services.payments.zynle_service.requests.post')
    def test_status_request_uses_nested_auth_and_data(self, post):
        response = Mock()
        response.json.return_value = {'response_code': '990'}
        post.return_value = response
        service = ZynleService(
            base_url='https://sandbox.example/jsonapi',
            api_key='key',
            api_id='id',
            merchant_id='merchant',
        )

        service.check_payment_status('DEP_1')

        self.assertEqual(post.call_args.kwargs['json'], {
            'auth': {
                'merchant_id': 'merchant',
                'api_id': 'id',
                'api_key': 'key',
                'channel': 'momo',
            },
            'data': {
                'method': 'checkPaymentStatus',
                'reference_no': 'DEP_1',
            },
        })

    @patch('services.payments.zynle_service.requests.post')
    def test_api_id_is_optional_and_omitted_when_blank(self, post):
        response = Mock()
        response.json.return_value = {'response_code': '120'}
        post.return_value = response
        service = ZynleService(
            base_url='https://payments.example/jsonapi',
            api_key='key',
            merchant_id='merchant',
        )

        service.momo_deposit(
            sender_id='260971234567', amount=Decimal('1.00'), reference_no='DEP_2'
        )

        auth = post.call_args.kwargs['json']['auth']
        self.assertNotIn('api_id', auth)
        self.assertTrue(service.configured)

    @patch('services.payments.zynle_service.requests.post')
    def test_sandbox_response_envelope_is_unwrapped(self, post):
        response = Mock()
        response.json.return_value = {
            'response': {
                'response_code': '120',
                'response_description': 'Transaction is initiated',
                'reference_no': 'DEP_1',
                'transaction_id': 9260667451,
            }
        }
        post.return_value = response
        service = ZynleService(
            base_url='https://sandbox.example/jsonapi',
            api_key='key',
            api_id='id',
            merchant_id='merchant',
        )

        result = service.momo_deposit(
            sender_id='260971234567', amount=Decimal('20.00'), reference_no='DEP_1'
        )

        self.assertEqual(result['response_code'], '120')
        self.assertEqual(result['transaction_id'], 9260667451)


@override_settings(ZYNLE_CALLBACK_TOKEN='private-callback-token')
class ZynleGatewayTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('zynle-user', password='pass1234')
        self.wallet, _ = Wallet.objects.get_or_create(user=self.user)
        self.deposit = Deposit.objects.create(
            user=self.user,
            wallet=self.wallet,
            amount=Decimal('10.00'),
            payment_method='ZYNLE_MOMO',
            payment_provider='zynle',
            payment_reference='ZYN_DEP_1',
            provider_transaction_id='TX-1',
            provider_payment_status='Pending',
            status='PROCESSING',
        )
        self.gateway = ZynleGateway(service=Mock())
        self.factory = RequestFactory()

    def _callback(self, token='private-callback-token'):
        return self.factory.post(
            f'/api/payments/zynle/webhook/?token={token}',
            data=json.dumps({
                'response_code': 100,
                'response_description': 'Successful Transaction',
                'reference_no': 'ZYN_DEP_1',
                'transaction_id': 'TX-1',
            }),
            content_type='application/json',
        )

    def test_callback_requires_private_token(self):
        result = self.gateway.handle_webhook(self._callback('wrong'))

        self.assertFalse(result.processed)
        self.deposit.refresh_from_db()
        self.assertEqual(self.deposit.status, 'PROCESSING')

    def test_success_callback_credits_wallet_once(self):
        first = self.gateway.handle_webhook(self._callback())
        second = self.gateway.handle_webhook(self._callback())

        self.assertTrue(first.processed)
        self.assertTrue(second.processed)
        self.deposit.refresh_from_db()
        self.wallet.refresh_from_db()
        self.assertEqual(self.deposit.status, 'COMPLETED')
        self.assertEqual(self.wallet.balance, Decimal('10.00'))
        self.assertEqual(
            Transaction.objects.filter(wallet=self.wallet, transaction_type='DEPOSIT').count(),
            1,
        )

    def test_documented_response_codes_are_normalized(self):
        self.assertEqual(ZynleGateway.normalize_status({'response_code': 100}), 'Successful')
        self.assertEqual(ZynleGateway.normalize_status({'response_code': 120}), 'Pending')
        self.assertEqual(ZynleGateway.normalize_status({'response_code': 990}), 'Pending')
        self.assertEqual(ZynleGateway.normalize_status({'response_code': 995}), 'Failed')
        self.assertEqual(ZynleGateway.normalize_status({'response_code': 9902}), 'Failed')
        self.assertEqual(
            ZynleGateway.normalize_status({'response': {'response_code': '120'}}),
            'Pending',
        )


class PaymentProviderSelectionTests(TestCase):
    def test_admin_setting_overrides_environment_default(self):
        PaymentGatewaySetting.objects.update_or_create(pk=1, defaults={'active_provider': 'zynle'})
        self.assertEqual(get_active_payment_provider(), 'zynle')
        self.assertEqual(get_payment_gateway('lipila').provider_name, 'lipila')
        self.assertEqual(get_payment_gateway('zynle').provider_name, 'zynle')

    @override_settings(
        ZYNLE_API_KEY='key',
        ZYNLE_API_ID='',
        ZYNLE_MERCHANT_ID='merchant',
    )
    def test_zynle_deposit_form_shows_mobile_number_field(self):
        user = get_user_model().objects.create_user('form-user', password='pass1234')
        PaymentGatewaySetting.objects.update_or_create(
            pk=1, defaults={'active_provider': 'zynle'}
        )
        self.client.force_login(user)

        response = self.client.get(reverse('deposit'))

        self.assertContains(response, 'ZynlePay Mobile Money (MoMo)')
        self.assertContains(response, 'mobileMoneyMethods.includes(methodSelect.value)')
        self.assertContains(response, 'name="mobile_number"')
