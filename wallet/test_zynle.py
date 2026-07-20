import json
from decimal import Decimal
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from services.payments.base import PaymentVerifyResult
from services.payments.factory import get_active_payment_provider, get_payment_gateway
from services.payments.zynle_gateway import ZynleGateway
from services.payments.zynle_service import ZynleService
from wallet.models import Deposit, PaymentGatewaySetting, Transaction, Wallet, Withdrawal


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
    def test_api_id_is_required_and_included_when_blank(self, post):
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
        self.assertEqual(auth['api_id'], '')
        self.assertFalse(service.configured)

    @patch('services.payments.zynle_service.requests.post')
    def test_momo_withdraw_sends_receiver_payload(self, post):
        response = Mock()
        response.json.return_value = {'response_code': '120', 'transaction_id': 'TX-WDR-1'}
        post.return_value = response
        service = ZynleService(
            base_url='https://sandbox.example/jsonapi',
            api_key='key',
            api_id='id',
            merchant_id='merchant',
        )

        service.momo_withdraw(
            receiver_id='260971234567', amount=Decimal('25.50'), reference_no='WDR_1'
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
                'method': 'runPayToEwallet',
                'receiver_id': '260971234567',
                'reference_no': 'WDR_1',
                'amount': '25.50',
            },
        })

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

    def _callback(self, token='private-callback-token', payload=None):
        return self.factory.post(
            f'/api/payments/zynle/webhook/?token={token}',
            data=json.dumps(payload or {
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

    def test_failure_callback_stores_provider_description(self):
        result = self.gateway.handle_webhook(self._callback(payload={
            'response_code': 995,
            'response_description': 'Insufficient funds',
            'reference_no': 'ZYN_DEP_1',
            'transaction_id': 'TX-1',
        }))

        self.assertTrue(result.processed)
        self.deposit.refresh_from_db()
        self.assertEqual(self.deposit.status, 'FAILED')
        self.assertEqual(self.deposit.failure_reason, 'Insufficient funds')

    def test_callback_without_code_does_not_fail_when_description_is_pending(self):
        result = self.gateway.handle_webhook(self._callback(payload={
            'response_description': 'Transaction is initiated',
            'reference_no': 'ZYN_DEP_1',
            'transaction_id': 'TX-1',
        }))

        self.assertTrue(result.processed)
        self.deposit.refresh_from_db()
        self.assertEqual(self.deposit.status, 'PROCESSING')
        self.assertEqual(self.deposit.provider_payment_status, 'Pending')

    def test_status_lookup_invalid_method_keeps_deposit_pending(self):
        self.gateway.service.check_payment_status.return_value = {
            'response_code': 995,
            'response_description': 'Invalid method',
            'reference_no': 'ZYN_DEP_1',
            'transaction_id': 'TX-1',
        }

        result = self.gateway.verify_payment(self.deposit)

        self.assertEqual(result.payment_status, 'Pending')
        self.deposit.refresh_from_db()
        self.assertEqual(self.deposit.status, 'PROCESSING')

    @patch('services.payments.factory.get_payment_gateway')
    def test_status_poll_does_not_verify_zynle_deposits(self, get_gateway):
        gateway = Mock()
        gateway.verify_payment.return_value = PaymentVerifyResult(
            success=False,
            payment_status='Failed',
            provider_transaction_id='TX-1',
            message='Invalid method',
            raw_response={
                'response_code': 995,
                'response_description': 'Invalid method',
                'reference_no': 'ZYN_DEP_1',
                'transaction_id': 'TX-1',
            },
        )
        get_gateway.return_value = gateway
        self.client.force_login(self.user)

        response = self.client.get(reverse('deposit_status_json', kwargs={'deposit_id': self.deposit.id}))

        self.assertEqual(response.status_code, 200)
        get_gateway.assert_not_called()
        self.deposit.refresh_from_db()
        self.assertEqual(self.deposit.status, 'PROCESSING')
        self.assertEqual(response.json()['status'], 'PROCESSING')

    def test_success_callback_completes_withdrawal_once(self):
        Wallet.objects.filter(id=self.wallet.id).update(balance=Decimal('25.00'))
        self.user.refresh_from_db()
        self.wallet.refresh_from_db()
        withdrawal = Withdrawal.objects.create(
            user=self.user,
            wallet=self.wallet,
            amount=Decimal('10.00'),
            payment_method='MOBILE_MONEY',
            account_details='260974221154|Airtel',
            status='PROCESSING',
            transaction_id='ZYN-TX-1',
            gateway_transaction_id='ZYN-TX-1',
            gateway_response={'gateway': 'zynle', 'reference_no': 'ZYN_WDR_1'},
        )
        request = self.factory.post(
            '/api/payments/zynle/webhook/?token=private-callback-token',
            data=json.dumps({
                'response_code': 100,
                'response_description': 'Successful Transaction',
                'reference_no': 'ZYN_WDR_1',
                'transaction_id': 'ZYN-TX-1',
            }),
            content_type='application/json',
        )

        first = self.gateway.handle_webhook(request)
        second = self.gateway.handle_webhook(request)

        self.assertTrue(first.processed)
        self.assertFalse(second.processed)
        self.assertEqual(first.withdrawal_id, withdrawal.id)
        withdrawal.refresh_from_db()
        self.wallet.refresh_from_db()
        self.assertEqual(withdrawal.status, 'COMPLETED')
        self.assertEqual(self.wallet.balance, Decimal('15.00'))
        self.assertEqual(
            Transaction.objects.filter(
                wallet=self.wallet,
                transaction_type='WITHDRAWAL',
                amount=Decimal('-10.00'),
            ).count(),
            1,
        )

    def test_process_withdrawal_preserves_zynle_response_fields(self):
        Wallet.objects.filter(id=self.wallet.id).update(balance=Decimal('25.00'))
        self.user.refresh_from_db()
        self.wallet.refresh_from_db()
        withdrawal = Withdrawal.objects.create(
            user=self.user,
            wallet=self.wallet,
            amount=Decimal('10.00'),
            payment_method='MOBILE_MONEY',
            account_details='260974221154|Airtel',
            status='PROCESSING',
        )
        self.gateway.service.configured = True
        self.gateway.service.momo_withdraw.return_value = {
            'response_code': '120',
            'response_description': 'Transaction is initiated',
            'reference_no': 'ZYN_WDR_1',
            'transaction_id': 'ZYN-TX-1',
            'operator_reference': 'AIR-REF-1',
            'receiver_id': '260974221154',
            'operator': 'Airtel',
            'transaction_date': '2025-01-30',
        }

        result = self.gateway.process_withdrawal(
            withdrawal,
            mobile_number='260974221154',
        )

        self.gateway.service.momo_withdraw.assert_called_once()
        call_kwargs = self.gateway.service.momo_withdraw.call_args.kwargs
        self.assertEqual(call_kwargs['receiver_id'], '260974221154')
        self.assertEqual(call_kwargs['amount'], Decimal('10.00'))
        self.assertTrue(call_kwargs['reference_no'].startswith('ZYN_WDR_1_'))
        self.assertTrue(result['success'])
        self.assertEqual(result['transaction_id'], 'ZYN-TX-1')
        self.assertEqual(result['gateway_response']['operator_reference'], 'AIR-REF-1')
        self.assertEqual(result['gateway_response']['receiver_id'], '260974221154')
        self.assertEqual(result['gateway_response']['gateway'], 'zynle')

    def test_documented_response_codes_are_normalized(self):
        self.assertEqual(ZynleGateway.normalize_status({'response_code': 100}), 'Successful')
        self.assertEqual(ZynleGateway.normalize_status({'response_code': 120}), 'Pending')
        self.assertEqual(ZynleGateway.normalize_status({'response_code': 990}), 'Pending')
        self.assertEqual(ZynleGateway.normalize_status({'response_code': 995}), 'Failed')
        self.assertEqual(ZynleGateway.normalize_status({'response_code': 9902}), 'Failed')
        self.assertEqual(ZynleGateway.normalize_status({'response_code': 9903}), 'Failed')
        self.assertEqual(
            ZynleGateway.normalize_status({'response': {'response_code': '120'}}),
            'Pending',
        )

    def test_response_message_falls_back_to_known_zynle_code(self):
        self.assertEqual(
            ZynleGateway.response_message({'response_code': 9903}),
            'Invalid Merchant API credentials or setup not complete',
        )


class PaymentProviderSelectionTests(TestCase):
    def test_admin_setting_overrides_environment_default(self):
        PaymentGatewaySetting.objects.update_or_create(pk=1, defaults={'active_provider': 'zynle'})
        self.assertEqual(get_active_payment_provider(), 'zynle')
        self.assertEqual(get_payment_gateway('lipila').provider_name, 'lipila')
        self.assertEqual(get_payment_gateway('zynle').provider_name, 'zynle')

    @override_settings(
        ZYNLE_API_KEY='key',
        ZYNLE_API_ID='id',
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
