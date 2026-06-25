"""Shared withdrawal processing helpers."""

import logging
from typing import Any, Dict, Optional

from django.db import transaction
from django.utils import timezone

from services.payments.lipila_service import LipilaService
from wallet.models import Withdrawal
from wallet.notifications import (
    notify_withdrawal_completed,
    notify_withdrawal_failed,
    notify_withdrawal_processing,
    notify_withdrawal_retry,
)
from wallet.payment_manager import get_payment_manager
from wallet.utils import refund_withdrawal_reservation

logger = logging.getLogger(__name__)


def process_withdrawal_now(withdrawal, *, actor=None) -> Dict[str, Any]:
    """
    Process one withdrawal through the configured payout gateway.

    A successful provider response may still be asynchronous. For Lipila
    disbursements, Pending means the payout was accepted and remains PROCESSING.
    """
    with transaction.atomic():
        withdrawal = Withdrawal.objects.select_for_update().get(id=withdrawal.id)

        if withdrawal.is_final:
            return {
                'processed': False,
                'status': withdrawal.status,
                'message': f'Withdrawal is already {withdrawal.status}.',
            }

        if withdrawal.status not in ('PENDING', 'PROCESSING'):
            return {
                'processed': False,
                'status': withdrawal.status,
                'message': f'Withdrawal is in {withdrawal.status} state.',
            }

        if withdrawal.status == 'PENDING':
            Withdrawal.objects.filter(id=withdrawal.id).update(
                status='PROCESSING',
                updated_at=timezone.now(),
            )
            withdrawal.refresh_from_db()
            notify_withdrawal_processing(withdrawal)

        result = get_payment_manager().process_withdrawal(withdrawal)
        gateway_response = result.get('gateway_response') or {}

        if result.get('success'):
            provider_status = LipilaService.normalize_status(
                LipilaService.extract_status(gateway_response)
            )
            next_status = 'COMPLETED' if provider_status == 'Successful' else 'PROCESSING'
            transaction_id = result.get('transaction_id')
            failure_reason = None

            if provider_status == 'Failed':
                next_status = _handle_failed_result(withdrawal, result)
                withdrawal.refresh_from_db()
                return {
                    'processed': True,
                    'status': withdrawal.status,
                    'gateway_status': provider_status,
                    'transaction_id': transaction_id,
                    'gateway_response': gateway_response,
                    'message': withdrawal.failure_reason or 'Withdrawal failed.',
                }

            Withdrawal.objects.filter(id=withdrawal.id).update(
                status=next_status,
                transaction_id=transaction_id,
                gateway_transaction_id=transaction_id,
                gateway_response=gateway_response,
                failure_reason=failure_reason,
                updated_at=timezone.now(),
            )
            withdrawal.refresh_from_db()
            if next_status == 'COMPLETED':
                notify_withdrawal_completed(withdrawal)

            logger.info(
                'Withdrawal %s processed via gateway: status=%s transaction_id=%s actor=%s',
                withdrawal.id,
                next_status,
                transaction_id,
                getattr(actor, 'username', None),
            )
            return {
                'processed': True,
                'status': withdrawal.status,
                'gateway_status': provider_status,
                'transaction_id': transaction_id,
                'gateway_response': gateway_response,
                'message': (
                    'Withdrawal completed.'
                    if next_status == 'COMPLETED'
                    else 'Withdrawal sent to provider and is processing.'
                ),
            }

        next_status = _handle_failed_result(withdrawal, result)
        withdrawal.refresh_from_db()
        return {
            'processed': True,
            'status': next_status,
            'gateway_response': gateway_response,
            'message': withdrawal.failure_reason or result.get('failure_reason') or 'Withdrawal failed.',
        }


def _handle_failed_result(withdrawal, result: Dict[str, Any]) -> str:
    gateway_response = result.get('gateway_response') or {}
    failure_reason = result.get('failure_reason') or 'Withdrawal processing failed'
    new_retry_count = withdrawal.retry_count + 1

    if new_retry_count >= withdrawal.max_retry_count:
        Withdrawal.objects.filter(id=withdrawal.id).update(
            status='FAILED',
            gateway_response=gateway_response,
            failure_reason=failure_reason,
            retry_count=new_retry_count,
            updated_at=timezone.now(),
        )
        refund_withdrawal_reservation(withdrawal, failure_reason)
        withdrawal.refresh_from_db()
        notify_withdrawal_failed(withdrawal, failure_reason)
        return 'FAILED'

    Withdrawal.objects.filter(id=withdrawal.id).update(
        status='PENDING',
        gateway_response=gateway_response,
        failure_reason=failure_reason,
        retry_count=new_retry_count,
        updated_at=timezone.now(),
    )
    withdrawal.refresh_from_db()
    notify_withdrawal_retry(withdrawal, new_retry_count, withdrawal.max_retry_count)
    return 'PENDING'


def apply_lipila_withdrawal_webhook(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Apply a Lipila disbursement webhook to a matching withdrawal."""
    if not isinstance(payload, dict):
        return None

    refs = []
    for value in (
        payload.get('referenceId'),
        payload.get('reference_id'),
        payload.get('identifier'),
        payload.get('transactionId'),
        payload.get('transaction_id'),
        payload.get('externalId'),
        payload.get('external_id'),
    ):
        value = str(value or '').strip()
        if value and value not in refs:
            refs.append(value)

    withdrawal = None
    for value in refs:
        withdrawal = (
            Withdrawal.objects.filter(transaction_id=value).first()
            or Withdrawal.objects.filter(gateway_transaction_id=value).first()
            or Withdrawal.objects.filter(gateway_response__reference_id=value).first()
            or Withdrawal.objects.filter(gateway_response__referenceId=value).first()
            or Withdrawal.objects.filter(gateway_response__identifier=value).first()
        )
        if withdrawal:
            break

    if not withdrawal:
        return None

    payment_status = LipilaService.normalize_status(LipilaService.extract_status(payload))
    message = str(payload.get('message') or '').strip()

    with transaction.atomic():
        withdrawal = Withdrawal.objects.select_for_update().get(id=withdrawal.id)
        if withdrawal.is_final:
            return {
                'processed': False,
                'withdrawal_id': withdrawal.id,
                'status': withdrawal.status,
                'message': f'Withdrawal already {withdrawal.status}.',
            }

        if payment_status == 'Successful':
            transaction_id = LipilaService.extract_transaction_id(payload) or withdrawal.transaction_id
            Withdrawal.objects.filter(id=withdrawal.id).update(
                status='COMPLETED',
                transaction_id=transaction_id,
                gateway_transaction_id=transaction_id,
                gateway_response=payload,
                failure_reason=None,
                updated_at=timezone.now(),
            )
            withdrawal.refresh_from_db()
            notify_withdrawal_completed(withdrawal)
            return {
                'processed': True,
                'withdrawal_id': withdrawal.id,
                'status': withdrawal.status,
                'message': 'Withdrawal completed by Lipila webhook.',
            }

        if payment_status == 'Failed':
            Withdrawal.objects.filter(id=withdrawal.id).update(
                status='FAILED',
                gateway_response=payload,
                failure_reason=message or 'Lipila disbursement failed',
                updated_at=timezone.now(),
            )
            refund_withdrawal_reservation(withdrawal, message or 'Lipila disbursement failed')
            withdrawal.refresh_from_db()
            notify_withdrawal_failed(withdrawal, withdrawal.failure_reason)
            return {
                'processed': True,
                'withdrawal_id': withdrawal.id,
                'status': withdrawal.status,
                'message': 'Withdrawal failed by Lipila webhook.',
            }

        Withdrawal.objects.filter(id=withdrawal.id).update(
            status='PROCESSING',
            gateway_response=payload,
            updated_at=timezone.now(),
        )
        return {
            'processed': True,
            'withdrawal_id': withdrawal.id,
            'status': 'PROCESSING',
            'message': 'Withdrawal still processing.',
        }
