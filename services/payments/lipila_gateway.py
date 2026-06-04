"""
Lipila payment gateway — server-to-server initiation, webhook confirmation only.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid
from typing import Any, Dict, Optional

from django.conf import settings
from django.urls import reverse
from django.utils import timezone

import requests

from services.payments.base import PaymentGateway, PaymentInitResult, PaymentVerifyResult, WebhookResult
from services.payments.lipila_service import LipilaService, get_lipila_service
from services.payments.url_utils import build_public_url

logger = logging.getLogger('payments.lipila')


class LipilaGateway(PaymentGateway):
    provider_name = 'lipila'

    def __init__(self, service: Optional[LipilaService] = None) -> None:
        self.service = service or get_lipila_service()

    def initiate_payment(
        self,
        deposit,
        request,
        *,
        mobile_number: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> PaymentInitResult:
        if bool(getattr(settings, 'LIPILA_MOCK_MODE', False)):
            return self._mock_init(deposit, request)

        secret = (
            getattr(settings, 'LIPILA_SECRET_KEY', '')
            or getattr(settings, 'LIPILA_API_KEY', '')
        ).strip()
        if not secret:
            return PaymentInitResult(
                success=False,
                provider=self.provider_name,
                payment_status='Failed',
                message='Lipila is not configured',
                failure_reason='LIPILA_SECRET_KEY is not set',
            )

        phone = self._normalize_phone(mobile_number or '')
        if deposit.payment_method == 'LIPILA_MOMO' and not phone:
            return PaymentInitResult(
                success=False,
                provider=self.provider_name,
                payment_status='Failed',
                message='Mobile number required',
                failure_reason='Valid Zambian mobile number required (26097xxxxxxx)',
            )

        reference_id = f'DEP_{deposit.id}_{int(timezone.now().timestamp())}'
        idem = idempotency_key or f'dep-{deposit.id}-{uuid.uuid4().hex[:12]}'
        callback_url = self._webhook_url(request)

        deposit.idempotency_key = idem
        deposit.payment_reference = reference_id
        deposit.payment_provider = 'lipila'
        deposit.provider_payment_status = 'Pending'
        deposit.save(update_fields=[
            'idempotency_key',
            'payment_reference',
            'payment_provider',
            'provider_payment_status',
        ])

        try:
            if deposit.payment_method == 'LIPILA_MOMO':
                resp = self.service.initiate_mobile_money(
                    reference_id=reference_id,
                    amount=float(deposit.amount),
                    account_number=phone,
                    currency=getattr(settings, 'LIPILA_CURRENCY', 'ZMW'),
                    narration=f'Deposit for {deposit.user.username}',
                    email=getattr(deposit.user, 'email', None),
                    callback_url=callback_url,
                    idempotency_key=idem,
                )
            else:
                # Card / other Lipila flows — use MoMo endpoint with email as fallback account id
                user = deposit.user
                account = phone or (user.email or f'user{user.id}@playyarena.local')
                resp = self.service.initiate_mobile_money(
                    reference_id=reference_id,
                    amount=float(deposit.amount),
                    account_number=account,
                    currency=getattr(settings, 'LIPILA_CURRENCY', 'ZMW'),
                    narration=f'Deposit for {user.username}',
                    email=user.email,
                    callback_url=callback_url,
                    idempotency_key=idem,
                )

            provider_txn = LipilaService.extract_transaction_id(resp) or reference_id
            lipila_status = LipilaService.normalize_status(str(resp.get('status', 'Pending')))
            failed = lipila_status == 'Failed'

            return PaymentInitResult(
                success=not failed,
                provider=self.provider_name,
                provider_transaction_id=provider_txn,
                payment_reference=reference_id,
                payment_status=lipila_status,
                payment_url=resp.get('cardRedirectionUrl') or resp.get('paymentUrl'),
                message=resp.get('message') or 'Payment initiated — awaiting webhook confirmation',
                failure_reason=None if not failed else (resp.get('message') or 'Payment failed'),
                raw_response=resp,
            )
        except requests.Timeout:
            logger.error('Lipila initiate timeout: deposit_id=%s', deposit.id, exc_info=True)
            return PaymentInitResult(
                success=False,
                provider=self.provider_name,
                payment_status='Pending',
                payment_reference=reference_id,
                message='Lipila request timed out',
                failure_reason='Payment provider timeout — retry or check status later',
            )
        except requests.RequestException as e:
            logger.error('Lipila initiate error: deposit_id=%s', deposit.id, exc_info=True)
            api_message = str(e)
            if hasattr(e, 'response') and e.response is not None:
                try:
                    body = e.response.json()
                    api_message = body.get('message') or body.get('error') or body.get('detail') or str(e)
                except Exception:
                    api_message = e.response.text[:300] or str(e)
            return PaymentInitResult(
                success=False,
                provider=self.provider_name,
                payment_status='Failed',
                payment_reference=reference_id,
                message=f'Lipila API error: {api_message}',
                failure_reason=api_message,
            )
    def verify_payment(self, deposit) -> PaymentVerifyResult:
        refs = []
        for ref in (
            deposit.payment_reference,
            deposit.provider_transaction_id,
            deposit.transaction_id,
        ):
            if ref and str(ref) not in refs:
                refs.append(str(ref))
        if isinstance(deposit.gateway_response, dict):
            for ref in (
                deposit.gateway_response.get('referenceId'),
                deposit.gateway_response.get('identifier'),
                deposit.gateway_response.get('transactionId'),
                deposit.gateway_response.get('externalId'),
            ):
                if ref and str(ref) not in refs:
                    refs.append(str(ref))

        if not refs:
            return PaymentVerifyResult(
                success=False,
                payment_status='Pending',
                message='No payment reference',
            )

        if refs[0].startswith('MOCK_') and bool(getattr(settings, 'LIPILA_MOCK_MODE', False)):
            return PaymentVerifyResult(
                success=True,
                payment_status='Successful',
                provider_transaction_id=refs[0],
                message='Mock payment',
                raw_response={'mock': True},
            )

        last_error = None
        pending_result = None
        try:
            for ref in refs:
                try:
                    resp = self.service.get_transaction_status(ref)
                except Exception as e:
                    last_error = e
                    logger.info('Lipila verify ref failed: deposit_id=%s ref=%s', deposit.id, ref)
                    continue

                normalized, msg = LipilaService.interpret_status(resp)
                lipila_status = LipilaService.normalize_status(
                    LipilaService.extract_status(resp) or normalized
                )
                result = PaymentVerifyResult(
                    success=normalized == 'COMPLETED',
                    payment_status=lipila_status,
                    provider_transaction_id=LipilaService.extract_transaction_id(resp) or ref,
                    message=msg,
                    raw_response=resp,
                )
                if normalized in ('COMPLETED', 'FAILED'):
                    return result
                if pending_result is None:
                    pending_result = result

            if pending_result is not None:
                return pending_result

            if last_error:
                logger.warning(
                    'Lipila verify unavailable: deposit_id=%s refs=%s last_error=%s',
                    deposit.id,
                    refs,
                    last_error,
                )
                return PaymentVerifyResult(
                    success=False,
                    payment_status='Pending',
                    message='Awaiting Lipila callback confirmation',
                )
        except Exception as e:
            logger.error('Lipila verify error: deposit_id=%s', deposit.id, exc_info=True)
            return PaymentVerifyResult(
                success=False,
                payment_status='Pending',
                message=str(e),
            )

        return PaymentVerifyResult(
            success=False,
            payment_status='Pending',
            message='Payment still pending',
        )

    def handle_webhook(self, request) -> WebhookResult:
        raw_body = request.body
        payload = self._parse_payload(request)
        if not payload:
            return WebhookResult(processed=False, message='Empty webhook payload')

        if not self._verify_webhook_signature(request, raw_body):
            logger.warning('Lipila webhook signature verification failed')
            return WebhookResult(processed=False, message='Invalid webhook signature')

        lipila_reference = str(
            payload.get('referenceId')
            or payload.get('reference_id')
            or ''
        ).strip()
        identifier = str(payload.get('identifier') or '').strip()
        external_id = str(payload.get('externalId') or payload.get('external_id') or '').strip()
        transaction_id = str(
            payload.get('transactionId')
            or payload.get('transaction_id')
            or lipila_reference
            or external_id
            or ''
        ).strip()
        status_raw = LipilaService.extract_status(payload)
        payment_status = LipilaService.normalize_status(status_raw)

        logger.info(
            'Lipila webhook received: referenceId=%s identifier=%s txn=%s status=%s',
            lipila_reference,
            identifier,
            transaction_id,
            payment_status,
        )

        from wallet.models import Deposit
        from wallet.payment_processing import apply_deposit_webhook_status

        deposit = None
        for value in (identifier, lipila_reference, transaction_id, external_id):
            if not value:
                continue
            deposit = (
                Deposit.objects.filter(payment_reference=value).first()
                or Deposit.objects.filter(provider_transaction_id=value).first()
                or Deposit.objects.filter(transaction_id=value).first()
            )
            if deposit:
                break

        if not deposit:
            logger.warning(
                'Lipila webhook: deposit not found referenceId=%s identifier=%s txn=%s externalId=%s',
                lipila_reference,
                identifier,
                transaction_id,
                external_id,
            )
            return WebhookResult(
                processed=True,
                message='Deposit not found',
                raw_payload=payload,
            )

        provider_transaction_id = None
        for candidate in (transaction_id, lipila_reference, external_id):
            if candidate and str(candidate) != str(deposit.payment_reference):
                provider_transaction_id = str(candidate)
                break

        applied = apply_deposit_webhook_status(
            deposit,
            payment_status=payment_status,
            provider_transaction_id=provider_transaction_id,
            raw_payload=payload,
            webhook_signature=request.headers.get('X-Signature')
            or request.headers.get('X-Webhook-Signature')
            or request.headers.get('webhook-signature'),
        )

        return WebhookResult(
            processed=applied['processed'],
            payment_status=payment_status,
            deposit_id=deposit.id,
            message=applied['message'],
            raw_payload=payload,
        )

    def _mock_init(self, deposit, request) -> PaymentInitResult:
        reference_id = f'MOCK_{deposit.id}_{int(timezone.now().timestamp())}'
        return PaymentInitResult(
            success=True,
            provider=self.provider_name,
            provider_transaction_id=reference_id,
            payment_reference=reference_id,
            payment_status='Pending',
            payment_url=build_public_url(
                request,
                reverse('lipila_callback_redirect') + f'?referenceId={reference_id}',
            ),
            message='Mock Lipila payment — webhook will confirm',
            raw_response={'mock': True},
        )

    @staticmethod
    def _webhook_url(request) -> str:
        configured = (getattr(settings, 'LIPILA_WEBHOOK_URL', '') or '').strip()
        if configured:
            return configured
        return build_public_url(request, reverse('api_lipila_webhook'))

    @staticmethod
    def _parse_payload(request) -> Dict[str, Any]:
        if request.content_type and 'json' in request.content_type:
            try:
                return json.loads(request.body.decode('utf-8') or '{}')
            except Exception:
                return {}
        merged = {**request.GET.dict(), **request.POST.dict()}
        return merged

    @staticmethod
    def _verify_webhook_signature(request, raw_body: bytes) -> bool:
        secret = (getattr(settings, 'LIPILA_WEBHOOK_SECRET', '') or '').strip()
        if not secret:
            return True
        signature = (
            request.headers.get('X-Signature')
            or request.headers.get('X-Webhook-Signature')
            or request.headers.get('webhook-signature')
            or request.headers.get('X-Lipila-Signature')
            or ''
        ).strip()
        if not signature:
            return False
        expected = hmac.new(
            secret.encode('utf-8'),
            raw_body,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(signature, expected) or hmac.compare_digest(
            signature,
            f'sha256={expected}',
        )

    @staticmethod
    def _normalize_phone(value: str) -> str:
        import re
        text = (value or '').strip().replace(' ', '')
        match = re.search(r'(\+?260\d{9}|0\d{9})', text)
        if match:
            digits = re.sub(r'\D', '', match.group(1))
            if digits.startswith('0') and len(digits) == 10:
                return '260' + digits[1:]
            if digits.startswith('260') and len(digits) == 12:
                return digits
        digits_only = re.sub(r'\D', '', text)
        if digits_only.startswith('260') and len(digits_only) == 12:
            return digits_only
        return ''
