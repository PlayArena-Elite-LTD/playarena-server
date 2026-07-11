"""ZynlePay mobile-money deposit gateway."""
from __future__ import annotations

import hmac
import json
import logging
import re
from typing import Any, Dict, Optional

import requests
from django.conf import settings
from django.utils import timezone

from services.payments.base import PaymentGateway, PaymentInitResult, PaymentVerifyResult, WebhookResult
from services.payments.zynle_service import ZynleService

logger = logging.getLogger('payments.zynle')


class ZynleGateway(PaymentGateway):
    provider_name = 'zynle'

    SUCCESS_CODES = {'100'}
    PENDING_CODES = {'120', '990'}

    def __init__(self, service: Optional[ZynleService] = None) -> None:
        self.service = service or ZynleService(
            base_url=getattr(settings, 'ZYNLE_BASE_URL', ''),
            api_key=getattr(settings, 'ZYNLE_API_KEY', ''),
            api_id=getattr(settings, 'ZYNLE_API_ID', ''),
            merchant_id=getattr(settings, 'ZYNLE_MERCHANT_ID', ''),
            channel=getattr(settings, 'ZYNLE_CHANNEL', 'momo'),
            deposit_method=getattr(settings, 'ZYNLE_DEPOSIT_METHOD', 'runBillPayment'),
            withdraw_method=getattr(settings, 'ZYNLE_WITHDRAW_METHOD', 'runPayToEwallet'),
            status_method=getattr(settings, 'ZYNLE_STATUS_METHOD', 'checkPaymentStatus'),
            timeout=getattr(settings, 'ZYNLE_TIMEOUT_SECONDS', 60),
        )

    def initiate_payment(
        self,
        deposit,
        request,
        *,
        mobile_number=None,
        idempotency_key=None,
    ) -> PaymentInitResult:
        if not self.service.configured:
            return PaymentInitResult(
                success=False, provider=self.provider_name, payment_status='Failed',
                message='Zynle is not configured',
                failure_reason='ZYNLE_API_KEY and ZYNLE_MERCHANT_ID are required',
            )

        phone = self._normalize_phone(mobile_number or '')
        if not phone:
            return PaymentInitResult(
                success=False, provider=self.provider_name, payment_status='Failed',
                message='Mobile number required',
                failure_reason='Valid Zambian mobile number required (26097xxxxxxx)',
            )

        reference = f'ZYN_DEP_{deposit.id}_{int(timezone.now().timestamp())}'
        deposit.payment_reference = reference
        deposit.payment_provider = self.provider_name
        deposit.provider_payment_status = 'Pending'
        deposit.save(update_fields=['payment_reference', 'payment_provider', 'provider_payment_status'])

        try:
            response = self.service.momo_deposit(
                sender_id=phone,
                amount=deposit.amount,
                reference_no=reference,
            )
            status = self.normalize_status(response)
            provider_txn = str(response.get('transaction_id') or '').strip() or reference
            message = str(response.get('response_description') or 'Payment initiated')
            logger.info(
                'Zynle initiate response: deposit_id=%s code=%s reference=%s transaction_id=%s operator=%s',
                deposit.id,
                response.get('response_code'),
                response.get('reference_no') or reference,
                provider_txn,
                response.get('operator'),
            )
            return PaymentInitResult(
                success=status != 'Failed',
                provider=self.provider_name,
                provider_transaction_id=provider_txn,
                payment_reference=str(response.get('reference_no') or reference),
                payment_status=status,
                message=message,
                failure_reason=message if status == 'Failed' else None,
                raw_response=response,
            )
        except requests.Timeout:
            logger.error('Zynle initiate timeout: deposit_id=%s', deposit.id, exc_info=True)
            return PaymentInitResult(
                success=True, provider=self.provider_name, payment_status='Pending',
                payment_reference=reference, message='Zynle request timed out',
                failure_reason='Payment provider timeout; check status before retrying',
            )
        except (requests.RequestException, ValueError) as exc:
            logger.error('Zynle initiate error: deposit_id=%s', deposit.id, exc_info=True)
            return PaymentInitResult(
                success=False, provider=self.provider_name, payment_status='Failed',
                payment_reference=reference, message='Zynle API error', failure_reason=str(exc),
            )

    def process_withdrawal(self, withdrawal, *, mobile_number: Optional[str] = None) -> Dict[str, Any]:
        if not self.service.configured:
            return {
                'success': False,
                'transaction_id': None,
                'gateway_response': {
                    'status': 'error',
                    'message': 'Zynle is not configured',
                    'gateway': self.provider_name,
                },
                'failure_reason': 'ZYNLE_API_KEY and ZYNLE_MERCHANT_ID are required',
            }

        phone = self._normalize_phone(mobile_number or '')
        if not phone:
            return {
                'success': False,
                'transaction_id': None,
                'gateway_response': {
                    'status': 'error',
                    'message': 'Invalid mobile number',
                    'gateway': self.provider_name,
                },
                'failure_reason': 'Account details must include a valid Zambian mobile money number (e.g. 26097xxxxxxx)',
            }

        reference = self._withdrawal_reference_no(withdrawal)
        try:
            response = self.service.momo_withdraw(
                receiver_id=phone,
                amount=withdrawal.amount,
                reference_no=reference,
            )
            status = self.normalize_status(response)
            provider_txn = str(response.get('transaction_id') or '').strip() or reference
            message = str(response.get('response_description') or 'Withdrawal initiated')
            gateway_response = {
                **response,
                'gateway': self.provider_name,
                'reference_no': str(response.get('reference_no') or reference),
            }
            logger.info(
                'Zynle withdrawal response: withdrawal_id=%s code=%s reference=%s transaction_id=%s operator=%s',
                withdrawal.id,
                response.get('response_code'),
                gateway_response['reference_no'],
                provider_txn,
                response.get('operator'),
            )
            return {
                'success': status != 'Failed',
                'transaction_id': provider_txn,
                'gateway_response': gateway_response,
                'failure_reason': message if status == 'Failed' else None,
            }
        except requests.Timeout as exc:
            logger.error('Zynle withdrawal timeout: withdrawal_id=%s', withdrawal.id, exc_info=True)
            return {
                'success': False,
                'transaction_id': reference,
                'gateway_response': {
                    'status': 'unknown_timeout',
                    'error': str(exc),
                    'gateway': self.provider_name,
                    'reference_no': reference,
                },
                'failure_reason': 'Zynle request timed out after submission; awaiting callback or manual verification.',
            }
        except (requests.RequestException, ValueError) as exc:
            logger.error('Zynle withdrawal error: withdrawal_id=%s', withdrawal.id, exc_info=True)
            return {
                'success': False,
                'transaction_id': None,
                'gateway_response': {'status': 'error', 'error': str(exc), 'gateway': self.provider_name},
                'failure_reason': f'Zynle API error: {str(exc)}',
            }

    def verify_payment(self, deposit) -> PaymentVerifyResult:
        reference = deposit.payment_reference or deposit.provider_transaction_id
        if not reference:
            return PaymentVerifyResult(False, 'Pending', message='No Zynle payment reference')
        try:
            response = self.service.check_payment_status(str(reference))
            payment_status = self.normalize_status(response)
            return PaymentVerifyResult(
                success=payment_status == 'Successful',
                payment_status=payment_status,
                provider_transaction_id=str(response.get('transaction_id') or '').strip() or None,
                message=str(response.get('response_description') or ''),
                raw_response=response,
            )
        except (requests.RequestException, ValueError) as exc:
            logger.warning('Zynle status check unavailable: deposit_id=%s error=%s', deposit.id, exc)
            return PaymentVerifyResult(False, 'Pending', message='Awaiting Zynle callback confirmation')

    def handle_webhook(self, request) -> WebhookResult:
        expected_token = str(getattr(settings, 'ZYNLE_CALLBACK_TOKEN', '') or '').strip()
        supplied_token = str(
            request.GET.get('token')
            or request.headers.get('X-Zynle-Callback-Token')
            or ''
        ).strip()
        if (
            not expected_token
            or not supplied_token
            or not hmac.compare_digest(expected_token, supplied_token)
        ):
            return WebhookResult(processed=False, message='Invalid Zynle callback token')

        raw_payload = self._parse_payload(request)
        payload = self._unwrap_payload(raw_payload)
        reference = str(payload.get('reference_no') or payload.get('referenceNo') or '').strip()
        transaction_id = str(payload.get('transaction_id') or payload.get('transactionId') or '').strip()
        if not reference and not transaction_id:
            return WebhookResult(
                processed=False,
                message='Missing Zynle transaction reference',
                raw_payload=raw_payload,
            )

        from wallet.models import Deposit
        from wallet.payment_processing import apply_deposit_webhook_status

        deposit = None
        for value in (reference, transaction_id):
            if value:
                deposit = (
                    Deposit.objects.filter(payment_provider='zynle', payment_reference=value).first()
                    or Deposit.objects.filter(payment_provider='zynle', provider_transaction_id=value).first()
                    or Deposit.objects.filter(payment_provider='zynle', transaction_id=value).first()
                )
            if deposit:
                break
        if not deposit:
            from wallet.withdrawal_processing import apply_zynle_withdrawal_webhook

            withdrawal_result = apply_zynle_withdrawal_webhook(payload)
            if withdrawal_result:
                return WebhookResult(
                    processed=bool(withdrawal_result.get('processed')),
                    payment_status=self.normalize_status(payload),
                    withdrawal_id=withdrawal_result.get('withdrawal_id'),
                    message=withdrawal_result.get('message', 'Withdrawal webhook handled'),
                    raw_payload=raw_payload,
                )
            return WebhookResult(
                processed=True,
                message='Zynle payment target not found',
                raw_payload=raw_payload,
            )

        payment_status = self.normalize_status(payload)
        applied = apply_deposit_webhook_status(
            deposit,
            payment_status=payment_status,
            provider_transaction_id=transaction_id or None,
            raw_payload=raw_payload,
            webhook_signature='callback-token',
        )
        return WebhookResult(
            processed=applied['processed'], payment_status=payment_status,
            deposit_id=deposit.id, message=applied['message'], raw_payload=raw_payload,
        )

    @classmethod
    def normalize_status(cls, payload: Dict[str, Any]) -> str:
        payload = cls._unwrap_payload(payload)
        code = str(payload.get('response_code') or payload.get('code') or '').strip()
        if code in cls.SUCCESS_CODES:
            return 'Successful'
        if code in cls.PENDING_CODES:
            return 'Pending'
        return 'Failed'

    @staticmethod
    def _unwrap_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
        wrapped = payload.get('response') if isinstance(payload, dict) else None
        return wrapped if isinstance(wrapped, dict) else payload

    @staticmethod
    def _parse_payload(request) -> Dict[str, Any]:
        try:
            payload = json.loads(request.body.decode('utf-8') or '{}')
            if isinstance(payload, dict):
                return payload
        except (ValueError, UnicodeDecodeError):
            pass
        return {**request.GET.dict(), **request.POST.dict()}

    @staticmethod
    def _normalize_phone(value: str) -> str:
        digits = re.sub(r'\D', '', value or '')
        if len(digits) == 10 and digits.startswith('0'):
            digits = '260' + digits[1:]
        return digits if len(digits) == 12 and digits.startswith('260') else ''

    @staticmethod
    def _withdrawal_reference_no(withdrawal) -> str:
        if isinstance(withdrawal.gateway_response, dict):
            for key in ('reference_no', 'referenceNo'):
                value = str(withdrawal.gateway_response.get(key) or '').strip()
                if value:
                    return value
        if withdrawal.transaction_id and str(withdrawal.transaction_id).startswith('ZYN_WDR_'):
            return str(withdrawal.transaction_id)
        return f'ZYN_WDR_{withdrawal.id}_{int(timezone.now().timestamp())}'
