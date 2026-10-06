"""
Idempotent deposit status updates from webhooks (authoritative confirmation).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from django.db import transaction
from django.utils import timezone

from wallet.models import Deposit
from wallet.utils import credit_deposit_wallet
from wallet.notifications import notify_deposit_completed, notify_deposit_failed

logger = logging.getLogger('payments')


def _provider_failure_reason(raw_payload: Optional[Dict[str, Any]]) -> Optional[str]:
    if not isinstance(raw_payload, dict):
        return None
    payload = raw_payload.get('response') if isinstance(raw_payload.get('response'), dict) else raw_payload
    for key in (
        'message',
        'response_description',
        'responseDescription',
        'description',
        'status_description',
        'statusDescription',
        'reason',
        'error',
    ):
        value = payload.get(key)
        if value:
            return str(value)
    return None


def _map_provider_status_to_deposit(provider_status: str) -> str:
    s = (provider_status or '').strip()
    if s == 'Successful':
        return 'COMPLETED'
    if s == 'Failed':
        return 'FAILED'
    return 'PROCESSING'


@transaction.atomic
def apply_deposit_webhook_status(
    deposit: Deposit,
    *,
    payment_status: str,
    provider_transaction_id: Optional[str] = None,
    raw_payload: Optional[Dict[str, Any]] = None,
    webhook_signature: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Idempotent webhook handler — only webhook (or verify_payment) may mark PAID/COMPLETED.
    """
    deposit = Deposit.objects.select_for_update().get(pk=deposit.pk)

    if deposit.status == 'COMPLETED':
        logger.info('Webhook idempotent skip: deposit %s already completed', deposit.id)
        return {'processed': True, 'message': 'Already completed', 'status': deposit.status}

    deposit.provider_payment_status = payment_status
    deposit.raw_webhook_payload = raw_payload or {}
    deposit.last_webhook_at = timezone.now()
    if provider_transaction_id:
        deposit.provider_transaction_id = provider_transaction_id
        deposit.transaction_id = deposit.transaction_id or provider_transaction_id
    if webhook_signature:
        deposit.webhook_signature = webhook_signature[:255]
        deposit.webhook_verified = True

    internal_status = _map_provider_status_to_deposit(payment_status)

    if internal_status == 'COMPLETED':
        deposit.status = 'COMPLETED'
        deposit.completed_at = timezone.now()
        deposit.failure_reason = None
        deposit.save()

        wallet, _transaction = credit_deposit_wallet(deposit)
        notify_deposit_completed(deposit)
        logger.info(
            'Deposit %s completed via webhook — user=%s amount=%s',
            deposit.id,
            deposit.user_id,
            deposit.amount,
        )
        return {'processed': True, 'message': 'Deposit completed', 'status': 'COMPLETED'}

    if internal_status == 'FAILED':
        deposit.status = 'FAILED'
        deposit.failure_reason = _provider_failure_reason(raw_payload) or 'Payment failed'
        deposit.save()
        notify_deposit_failed(deposit, failure_reason=deposit.failure_reason)
        logger.info('Deposit %s failed via webhook: %s', deposit.id, deposit.failure_reason)
        return {'processed': True, 'message': 'Deposit failed', 'status': 'FAILED'}

    deposit.status = 'PROCESSING'
    deposit.save()
    logger.info('Deposit %s still pending after webhook', deposit.id)
    return {'processed': True, 'message': 'Still pending', 'status': 'PROCESSING'}
