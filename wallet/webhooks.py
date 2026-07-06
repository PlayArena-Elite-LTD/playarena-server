"""
Payment gateway webhook handlers.

This module handles webhook callbacks from payment gateways (Paystack, Flutterwave)
to update deposit and withdrawal status automatically.

Security features:
- Webhook signature verification
- Idempotency checks (prevent duplicate processing)
- Atomic transactions
- Comprehensive logging
"""

import json
import hmac
import hashlib
import logging
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_http_methods
from django.db import transaction
from django.conf import settings
from django.utils import timezone
from django.contrib import messages

from wallet.models import Deposit, Withdrawal, Transaction, Wallet
from wallet.utils import refund_withdrawal_reservation, process_withdrawal_and_debit_wallet
from services.payments.factory import get_payment_gateway
from wallet.notifications import (
    notify_deposit_completed,
    notify_deposit_failed,
    notify_withdrawal_completed,
    notify_withdrawal_failed
)

logger = logging.getLogger(__name__)


def verify_paystack_signature(request):
    """
    Verify Paystack webhook signature.
    
    Args:
        request: Django HttpRequest object
        
    Returns:
        bool: True if signature is valid, False otherwise
    """
    paystack_secret = getattr(settings, 'PAYSTACK_SECRET_KEY', None)
    if not paystack_secret:
        logger.warning('Paystack secret key not configured for webhook verification')
        return False
    
    signature = request.headers.get('X-Paystack-Signature', '')
    if not signature:
        return False
    
    # Calculate expected signature
    body = request.body
    expected_signature = hmac.new(
        paystack_secret.encode('utf-8'),
        body,
        hashlib.sha512
    ).hexdigest()
    
    # Use constant-time comparison to prevent timing attacks
    return hmac.compare_digest(signature, expected_signature)


def verify_flutterwave_signature(request):
    """
    Verify Flutterwave webhook signature.
    
    Args:
        request: Django HttpRequest object
        
    Returns:
        bool: True if signature is valid, False otherwise
    """
    flutterwave_secret = getattr(settings, 'FLUTTERWAVE_SECRET_KEY', None)
    if not flutterwave_secret:
        logger.warning('Flutterwave secret key not configured for webhook verification')
        return False
    
    signature = request.headers.get('verif-hash', '')
    if not signature:
        return False
    
    # Calculate expected signature
    body = request.body
    expected_signature = hashlib.sha256(
        (flutterwave_secret + body.decode('utf-8')).encode('utf-8')
    ).hexdigest()
    
    # Use constant-time comparison to prevent timing attacks
    return hmac.compare_digest(signature, expected_signature)


@transaction.atomic
def _complete_deposit(deposit: Deposit, completed_via: str, gateway_payload: dict):
    # Idempotency
    if deposit.status == 'COMPLETED':
        return False

    deposit.status = 'COMPLETED'
    deposit.completed_at = timezone.now()
    deposit.gateway_response = gateway_payload or {}
    deposit.failure_reason = None
    deposit.save()

    wallet = deposit.wallet
    wallet.balance += deposit.amount
    wallet.save()

    Transaction.objects.create(
        wallet=wallet,
        amount=deposit.amount,
        transaction_type='DEPOSIT',
        description=f"Deposit of ZMW {deposit.amount} via {deposit.get_payment_method_display()}",
    )

    notify_deposit_completed(deposit)

    from audit.utils import log_action
    log_action(
        action='deposit_completed',
        user=deposit.user,
        details={
            'deposit_id': deposit.id,
            'amount': str(deposit.amount),
            'payment_method': deposit.payment_method,
            'transaction_id': deposit.transaction_id,
            'completed_via': completed_via,
            'new_balance': str(wallet.balance),
        },
    )
    return True


@transaction.atomic
def _fail_deposit(deposit: Deposit, failed_via: str, reason: str, gateway_payload: dict):
    if deposit.status in ('COMPLETED', 'FAILED', 'CANCELLED'):
        return False

    deposit.status = 'FAILED'
    deposit.failure_reason = reason or 'Payment failed'
    deposit.gateway_response = gateway_payload or {}
    deposit.save()

    notify_deposit_failed(deposit, failure_reason=deposit.failure_reason)

    from audit.utils import log_action
    log_action(
        action='deposit_failed',
        user=deposit.user,
        details={
            'deposit_id': deposit.id,
            'amount': str(deposit.amount),
            'payment_method': deposit.payment_method,
            'transaction_id': deposit.transaction_id,
            'failure_reason': deposit.failure_reason,
            'failed_via': failed_via,
        },
    )
    return True


def _lipila_reference_id_from_request(request) -> str | None:
    """Extract Lipila referenceId from query, form, or JSON body."""
    reference_id = (
        request.GET.get('referenceId')
        or request.GET.get('reference_id')
        or request.POST.get('referenceId')
        or request.POST.get('reference_id')
    )
    if reference_id:
        return str(reference_id).strip()
    try:
        body = json.loads(request.body.decode('utf-8') or '{}')
        if isinstance(body, dict):
            return str(
                body.get('referenceId')
                or body.get('reference_id')
                or ''
            ).strip() or None
    except Exception:
        pass
    return None


def _find_deposit_by_lipila_reference(reference_id: str):
    return (
        Deposit.objects.filter(payment_reference=str(reference_id)).first()
        or Deposit.objects.filter(transaction_id=str(reference_id)).first()
    )


@csrf_exempt
@require_http_methods(["GET", "POST"])
def lipila_callback(request):
    """
    User redirect / legacy callback URL — does NOT confirm payment.

    Wallet credit happens only via POST /api/payments/lipila/webhook/.
    """
    from django.shortcuts import redirect

    reference_id = _lipila_reference_id_from_request(request)
    deposit = _find_deposit_by_lipila_reference(reference_id) if reference_id else None

    if request.method == 'POST':
        gateway = get_payment_gateway()
        result = gateway.handle_webhook(request)
        return JsonResponse({
            'status': 'ok' if result.processed else 'ignored',
            'message': result.message,
        })

    if deposit:
        return redirect('deposit_pending', deposit_id=deposit.id)
    messages.info(request, 'Payment pending. Waiting for confirmation from provider.')
    return redirect('wallet')


@csrf_exempt
@require_POST
def paystack_webhook(request):
    """
    Handle Paystack webhook events.
    
    Documentation: https://paystack.com/docs/api/events/
    
    Events handled:
    - charge.success: Deposit completed
    - transfer.success: Withdrawal completed
    - transfer.failed: Withdrawal failed
    - transfer.reversed: Withdrawal reversed
    """
    # Verify webhook signature
    if not verify_paystack_signature(request):
        logger.warning('Invalid Paystack webhook signature')
        return JsonResponse({'status': 'error', 'message': 'Invalid signature'}, status=401)
    
    try:
        data = json.loads(request.body)
        event = data.get('event')
        
        if not event:
            logger.warning('Paystack webhook missing event type')
            return JsonResponse({'status': 'error', 'message': 'Missing event'}, status=400)
        
        logger.info(f'Received Paystack webhook: {event}')
        
        # Handle different event types
        if event == 'charge.success':
            return handle_paystack_deposit_success(data)
        elif event == 'transfer.success':
            return handle_paystack_withdrawal_success(data)
        elif event == 'transfer.failed':
            return handle_paystack_withdrawal_failed(data)
        elif event == 'transfer.reversed':
            return handle_paystack_withdrawal_reversed(data)
        else:
            logger.info(f'Unhandled Paystack event: {event}')
            return JsonResponse({'status': 'ok', 'message': 'Event not handled'})
    
    except json.JSONDecodeError as e:
        logger.error(f'Invalid JSON in Paystack webhook: {str(e)}')
        return JsonResponse({'status': 'error', 'message': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f'Error processing Paystack webhook: {str(e)}', exc_info=True)
        return JsonResponse({'status': 'error', 'message': 'Processing error'}, status=500)


@csrf_exempt
@require_POST
def flutterwave_webhook(request):
    """
    Handle Flutterwave webhook events.
    
    Documentation: https://developer.flutterwave.com/docs/events
    
    Events handled:
    - charge.completed: Deposit completed
    - transfer.completed: Withdrawal completed
    - transfer.failed: Withdrawal failed
    """
    # Verify webhook signature
    if not verify_flutterwave_signature(request):
        logger.warning('Invalid Flutterwave webhook signature')
        return JsonResponse({'status': 'error', 'message': 'Invalid signature'}, status=401)
    
    try:
        data = json.loads(request.body)
        event_type = data.get('event')
        
        if not event_type:
            logger.warning('Flutterwave webhook missing event type')
            return JsonResponse({'status': 'error', 'message': 'Missing event'}, status=400)
        
        logger.info(f'Received Flutterwave webhook: {event_type}')
        
        # Handle different event types
        if event_type == 'charge.completed':
            return handle_flutterwave_deposit_success(data)
        elif event_type == 'transfer.completed':
            return handle_flutterwave_withdrawal_success(data)
        elif event_type == 'transfer.failed':
            return handle_flutterwave_withdrawal_failed(data)
        else:
            logger.info(f'Unhandled Flutterwave event: {event_type}')
            return JsonResponse({'status': 'ok', 'message': 'Event not handled'})
    
    except json.JSONDecodeError as e:
        logger.error(f'Invalid JSON in Flutterwave webhook: {str(e)}')
        return JsonResponse({'status': 'error', 'message': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f'Error processing Flutterwave webhook: {str(e)}', exc_info=True)
        return JsonResponse({'status': 'error', 'message': 'Processing error'}, status=500)


@transaction.atomic
def handle_paystack_deposit_success(data):
    """Handle Paystack deposit success webhook"""
    charge_data = data.get('data', {})
    reference = charge_data.get('reference')
    
    if not reference:
        logger.warning('Paystack deposit webhook missing reference')
        return JsonResponse({'status': 'error', 'message': 'Missing reference'}, status=400)
    
    try:
        # Find deposit by transaction_id
        deposit = Deposit.objects.get(transaction_id=reference)
        
        # Check if already processed (idempotency)
        if deposit.status == 'COMPLETED':
            logger.info(f'Deposit {deposit.id} already completed, ignoring webhook')
            return JsonResponse({'status': 'ok', 'message': 'Already processed'})
        
        # Update deposit status
        deposit.status = 'COMPLETED'
        deposit.save()
        
        # Update wallet balance
        wallet = deposit.wallet
        wallet.balance += deposit.amount
        wallet.save()
        
        # Create transaction record
        Transaction.objects.create(
            wallet=wallet,
            amount=deposit.amount,
            transaction_type='DEPOSIT',
            description=f"Deposit of ZMW {deposit.amount} via {deposit.get_payment_method_display()}"
        )
        
        # Send notification
        notify_deposit_completed(deposit)
        
        # Audit log: Deposit completed via webhook
        from audit.utils import log_action
        log_action(
            action='deposit_completed',
            user=deposit.user,
            details={
                'deposit_id': deposit.id,
                'amount': str(deposit.amount),
                'payment_method': deposit.payment_method,
                'transaction_id': deposit.transaction_id,
                'completed_via': 'paystack_webhook',
                'new_balance': str(wallet.balance),
            }
        )
        
        logger.info(f'Deposit {deposit.id} completed via Paystack webhook')
        return JsonResponse({'status': 'ok'})
    
    except Deposit.DoesNotExist:
        logger.warning(f'Deposit not found for Paystack reference: {reference}')
        return JsonResponse({'status': 'error', 'message': 'Deposit not found'}, status=404)
    except Exception as e:
        logger.error(f'Error processing Paystack deposit webhook: {str(e)}', exc_info=True)
        return JsonResponse({'status': 'error', 'message': 'Processing error'}, status=500)


@transaction.atomic
def handle_paystack_withdrawal_success(data):
    """Handle Paystack withdrawal success webhook"""
    transfer_data = data.get('data', {})
    transfer_code = transfer_data.get('transfer_code') or transfer_data.get('reference')
    
    if not transfer_code:
        logger.warning('Paystack withdrawal webhook missing transfer code')
        return JsonResponse({'status': 'error', 'message': 'Missing transfer code'}, status=400)
    
    try:
        # Find withdrawal by transaction_id or gateway_transaction_id
        withdrawal = Withdrawal.objects.filter(
            transaction_id=transfer_code
        ).first() or Withdrawal.objects.filter(
            gateway_transaction_id=transfer_code
        ).first()
        
        if not withdrawal:
            logger.warning(f'Withdrawal not found for Paystack transfer code: {transfer_code}')
            return JsonResponse({'status': 'error', 'message': 'Withdrawal not found'}, status=404)
        
        # Check if already processed (idempotency)
        if withdrawal.status == 'COMPLETED':
            logger.info(f'Withdrawal {withdrawal.id} already completed, ignoring webhook')
            return JsonResponse({'status': 'ok', 'message': 'Already processed'})
        
        completion = process_withdrawal_and_debit_wallet(
            withdrawal,
            {
                'transaction_id': transfer_code,
                'transfer_code': transfer_code,
                'gateway_response': transfer_data,
            },
        )
        if not completion.get('success'):
            return JsonResponse(
                {'status': 'error', 'message': completion.get('message') or 'Wallet debit failed'},
                status=400,
            )
        withdrawal.refresh_from_db()
        wallet = withdrawal.wallet
        
        # Send notification
        notify_withdrawal_completed(withdrawal)
        
        # Audit log: Withdrawal completed via webhook
        from audit.utils import log_action
        log_action(
            action='withdrawal_completed',
            user=withdrawal.user,
            details={
                'withdrawal_id': withdrawal.id,
                'amount': str(withdrawal.amount),
                'payment_method': withdrawal.payment_method,
                'transaction_id': withdrawal.transaction_id,
                'completed_via': 'paystack_webhook',
                'new_balance': str(wallet.balance),
            }
        )
        
        logger.info(f'Withdrawal {withdrawal.id} completed via Paystack webhook')
        return JsonResponse({'status': 'ok'})
    
    except Exception as e:
        logger.error(f'Error processing Paystack withdrawal webhook: {str(e)}', exc_info=True)
        return JsonResponse({'status': 'error', 'message': 'Processing error'}, status=500)


@transaction.atomic
def handle_paystack_withdrawal_failed(data):
    """Handle Paystack withdrawal failed webhook"""
    transfer_data = data.get('data', {})
    transfer_code = transfer_data.get('transfer_code') or transfer_data.get('reference')
    reason = transfer_data.get('reason') or 'Payment gateway error'
    
    if not transfer_code:
        logger.warning('Paystack withdrawal failed webhook missing transfer code')
        return JsonResponse({'status': 'error', 'message': 'Missing transfer code'}, status=400)
    
    try:
        # Find withdrawal
        withdrawal = Withdrawal.objects.filter(
            transaction_id=transfer_code
        ).first() or Withdrawal.objects.filter(
            gateway_transaction_id=transfer_code
        ).first()
        
        if not withdrawal:
            logger.warning(f'Withdrawal not found for Paystack transfer code: {transfer_code}')
            return JsonResponse({'status': 'error', 'message': 'Withdrawal not found'}, status=404)
        
        # Check if already in final state
        if withdrawal.is_final:
            logger.info(f'Withdrawal {withdrawal.id} already in final state, ignoring webhook')
            return JsonResponse({'status': 'ok', 'message': 'Already processed'})
        
        # Update withdrawal status
        withdrawal.status = 'FAILED'
        withdrawal.failure_reason = reason
        withdrawal.gateway_response = transfer_data
        withdrawal.save()
        refund_result = refund_withdrawal_reservation(withdrawal, reason)
        
        # Send notification
        notify_withdrawal_failed(withdrawal, reason)
        
        # Audit log: Withdrawal failed via webhook
        from audit.utils import log_action
        log_action(
            action='withdrawal_failed',
            user=withdrawal.user,
            details={
                'withdrawal_id': withdrawal.id,
                'amount': str(withdrawal.amount),
                'payment_method': withdrawal.payment_method,
                'failure_reason': reason,
                'failed_via': 'paystack_webhook',
                'refunded': refund_result['refunded'],
                'new_balance': str(refund_result['new_balance']),
            }
        )
        
        logger.info(f'Withdrawal {withdrawal.id} failed via Paystack webhook: {reason}')
        return JsonResponse({'status': 'ok'})
    
    except Exception as e:
        logger.error(f'Error processing Paystack withdrawal failed webhook: {str(e)}', exc_info=True)
        return JsonResponse({'status': 'error', 'message': 'Processing error'}, status=500)


@transaction.atomic
def handle_paystack_withdrawal_reversed(data):
    """Handle Paystack withdrawal reversed webhook"""
    transfer_data = data.get('data', {})
    transfer_code = transfer_data.get('transfer_code') or transfer_data.get('reference')
    
    if not transfer_code:
        logger.warning('Paystack withdrawal reversed webhook missing transfer code')
        return JsonResponse({'status': 'error', 'message': 'Missing transfer code'}, status=400)
    
    try:
        # Find withdrawal
        withdrawal = Withdrawal.objects.filter(
            transaction_id=transfer_code
        ).first() or Withdrawal.objects.filter(
            gateway_transaction_id=transfer_code
        ).first()
        
        if not withdrawal:
            logger.warning(f'Withdrawal not found for Paystack transfer code: {transfer_code}')
            return JsonResponse({'status': 'error', 'message': 'Withdrawal not found'}, status=404)
        
        # If withdrawal was completed, reverse it
        if withdrawal.status == 'COMPLETED':
            refund_result = refund_withdrawal_reservation(
                withdrawal,
                f'Withdrawal reversed by payment gateway ({transfer_code})',
            )
            
            # Update withdrawal status
            withdrawal.status = 'FAILED'
            withdrawal.failure_reason = 'Withdrawal reversed by payment gateway'
            withdrawal.gateway_response = transfer_data
            withdrawal.save()
            
            # Audit log: Withdrawal reversed via webhook
            from audit.utils import log_action
            log_action(
                action='withdrawal_reversed',
                user=withdrawal.user,
                details={
                    'withdrawal_id': withdrawal.id,
                    'amount': str(withdrawal.amount),
                    'payment_method': withdrawal.payment_method,
                    'transaction_id': transfer_code,
                    'reversed_via': 'paystack_webhook',
                    'refunded': refund_result['refunded'],
                    'new_balance': str(refund_result['new_balance']),
                }
            )
            
            logger.info(f'Withdrawal {withdrawal.id} reversed via Paystack webhook')
        
        return JsonResponse({'status': 'ok'})
    
    except Exception as e:
        logger.error(f'Error processing Paystack withdrawal reversed webhook: {str(e)}', exc_info=True)
        return JsonResponse({'status': 'error', 'message': 'Processing error'}, status=500)


@transaction.atomic
def handle_flutterwave_deposit_success(data):
    """Handle Flutterwave deposit success webhook"""
    charge_data = data.get('data', {})
    tx_ref = charge_data.get('tx_ref')
    
    if not tx_ref:
        logger.warning('Flutterwave deposit webhook missing tx_ref')
        return JsonResponse({'status': 'error', 'message': 'Missing tx_ref'}, status=400)
    
    try:
        # Find deposit by transaction_id
        deposit = Deposit.objects.get(transaction_id=tx_ref)
        
        # Check if already processed
        if deposit.status == 'COMPLETED':
            logger.info(f'Deposit {deposit.id} already completed, ignoring webhook')
            return JsonResponse({'status': 'ok', 'message': 'Already processed'})
        
        # Update deposit status
        deposit.status = 'COMPLETED'
        deposit.save()
        
        # Update wallet balance
        wallet = deposit.wallet
        wallet.balance += deposit.amount
        wallet.save()
        
        # Create transaction record
        Transaction.objects.create(
            wallet=wallet,
            amount=deposit.amount,
            transaction_type='DEPOSIT',
            description=f"Deposit of ZMW {deposit.amount} via {deposit.get_payment_method_display()}"
        )
        
        # Send notification
        notify_deposit_completed(deposit)
        
        # Audit log: Deposit completed via webhook
        from audit.utils import log_action
        log_action(
            action='deposit_completed',
            user=deposit.user,
            details={
                'deposit_id': deposit.id,
                'amount': str(deposit.amount),
                'payment_method': deposit.payment_method,
                'transaction_id': deposit.transaction_id,
                'completed_via': 'flutterwave_webhook',
                'new_balance': str(wallet.balance),
            }
        )
        
        logger.info(f'Deposit {deposit.id} completed via Flutterwave webhook')
        return JsonResponse({'status': 'ok'})
    
    except Deposit.DoesNotExist:
        logger.warning(f'Deposit not found for Flutterwave tx_ref: {tx_ref}')
        return JsonResponse({'status': 'error', 'message': 'Deposit not found'}, status=404)
    except Exception as e:
        logger.error(f'Error processing Flutterwave deposit webhook: {str(e)}', exc_info=True)
        return JsonResponse({'status': 'error', 'message': 'Processing error'}, status=500)


@transaction.atomic
def handle_flutterwave_withdrawal_success(data):
    """Handle Flutterwave withdrawal success webhook"""
    transfer_data = data.get('data', {})
    transfer_id = transfer_data.get('id') or transfer_data.get('reference')
    
    if not transfer_id:
        logger.warning('Flutterwave withdrawal webhook missing transfer ID')
        return JsonResponse({'status': 'error', 'message': 'Missing transfer ID'}, status=400)
    
    try:
        # Find withdrawal
        withdrawal = Withdrawal.objects.filter(
            transaction_id=str(transfer_id)
        ).first() or Withdrawal.objects.filter(
            gateway_transaction_id=str(transfer_id)
        ).first()
        
        if not withdrawal:
            logger.warning(f'Withdrawal not found for Flutterwave transfer ID: {transfer_id}')
            return JsonResponse({'status': 'error', 'message': 'Withdrawal not found'}, status=404)
        
        # Check if already processed
        if withdrawal.status == 'COMPLETED':
            logger.info(f'Withdrawal {withdrawal.id} already completed, ignoring webhook')
            return JsonResponse({'status': 'ok', 'message': 'Already processed'})
        
        completion = process_withdrawal_and_debit_wallet(
            withdrawal,
            {
                'transaction_id': str(transfer_id),
                'gateway_response': transfer_data,
            },
        )
        if not completion.get('success'):
            return JsonResponse(
                {'status': 'error', 'message': completion.get('message') or 'Wallet debit failed'},
                status=400,
            )
        withdrawal.refresh_from_db()
        wallet = withdrawal.wallet
        
        # Send notification
        notify_withdrawal_completed(withdrawal)
        
        # Audit log: Withdrawal completed via webhook
        from audit.utils import log_action
        log_action(
            action='withdrawal_completed',
            user=withdrawal.user,
            details={
                'withdrawal_id': withdrawal.id,
                'amount': str(withdrawal.amount),
                'payment_method': withdrawal.payment_method,
                'transaction_id': withdrawal.transaction_id,
                'completed_via': 'flutterwave_webhook',
                'new_balance': str(wallet.balance),
            }
        )
        
        logger.info(f'Withdrawal {withdrawal.id} completed via Flutterwave webhook')
        return JsonResponse({'status': 'ok'})
    
    except Exception as e:
        logger.error(f'Error processing Flutterwave withdrawal webhook: {str(e)}', exc_info=True)
        return JsonResponse({'status': 'error', 'message': 'Processing error'}, status=500)


@transaction.atomic
def handle_flutterwave_withdrawal_failed(data):
    """Handle Flutterwave withdrawal failed webhook"""
    transfer_data = data.get('data', {})
    transfer_id = transfer_data.get('id') or transfer_data.get('reference')
    reason = transfer_data.get('complete_message') or 'Payment gateway error'
    
    if not transfer_id:
        logger.warning('Flutterwave withdrawal failed webhook missing transfer ID')
        return JsonResponse({'status': 'error', 'message': 'Missing transfer ID'}, status=400)
    
    try:
        # Find withdrawal
        withdrawal = Withdrawal.objects.filter(
            transaction_id=str(transfer_id)
        ).first() or Withdrawal.objects.filter(
            gateway_transaction_id=str(transfer_id)
        ).first()
        
        if not withdrawal:
            logger.warning(f'Withdrawal not found for Flutterwave transfer ID: {transfer_id}')
            return JsonResponse({'status': 'error', 'message': 'Withdrawal not found'}, status=404)
        
        # Check if already in final state
        if withdrawal.is_final:
            logger.info(f'Withdrawal {withdrawal.id} already in final state, ignoring webhook')
            return JsonResponse({'status': 'ok', 'message': 'Already processed'})
        
        # Update withdrawal status
        withdrawal.status = 'FAILED'
        withdrawal.failure_reason = reason
        withdrawal.gateway_response = transfer_data
        withdrawal.save()
        refund_result = refund_withdrawal_reservation(withdrawal, reason)
        
        # Send notification
        notify_withdrawal_failed(withdrawal, reason)
        
        # Audit log: Withdrawal failed via webhook
        from audit.utils import log_action
        log_action(
            action='withdrawal_failed',
            user=withdrawal.user,
            details={
                'withdrawal_id': withdrawal.id,
                'amount': str(withdrawal.amount),
                'payment_method': withdrawal.payment_method,
                'failure_reason': reason,
                'failed_via': 'flutterwave_webhook',
                'refunded': refund_result['refunded'],
                'new_balance': str(refund_result['new_balance']),
            }
        )
        
        logger.info(f'Withdrawal {withdrawal.id} failed via Flutterwave webhook: {reason}')
        return JsonResponse({'status': 'ok'})
    
    except Exception as e:
        logger.error(f'Error processing Flutterwave withdrawal failed webhook: {str(e)}', exc_info=True)
        return JsonResponse({'status': 'error', 'message': 'Processing error'}, status=500)
