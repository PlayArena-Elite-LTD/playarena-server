"""
Utility functions for wallet operations, transaction reconciliation and auditing.
"""
from decimal import Decimal
from django.db import transaction
from django.db.models import Sum, Q
from django.utils import timezone
from datetime import timedelta
import logging

from .models import Wallet, Transaction, Deposit, Withdrawal

logger = logging.getLogger(__name__)


def find_withdrawal_debit(withdrawal):
    """Return the wallet debit transaction for a withdrawal, if one exists."""
    return Transaction.objects.filter(
        wallet=withdrawal.wallet,
        amount=-withdrawal.amount,
        transaction_type='WITHDRAWAL',
        created_at__gte=withdrawal.created_at,
    ).filter(
        Q(description__startswith='Withdrawal request')
        | Q(description__startswith=f"Withdrawal of ZMW {withdrawal.amount}")
    ).first()


def build_public_url(request, path_or_url: str) -> str:
    from services.payments.url_utils import build_public_url as _build
    return _build(request, path_or_url)


def initialize_deposit_payment(deposit, request, mobile_number=None):
    """
    Initialize payment via the admin-selected deposit gateway.

    Never marks deposit COMPLETED here — webhook confirms payment.
    """
    if deposit.payment_method not in ('LIPILA', 'LIPILA_MOMO', 'ZYNLE_MOMO'):
        return {
            'initialized': False,
            'success': True,
            'payment_url': None,
            'payment_reference': None,
            'order_id': deposit.id,
            'payment_status': None,
            'message': 'Deposit created. Awaiting manual processing.',
            'failure_reason': None,
        }

    from services.payments.factory import get_active_payment_provider, get_payment_gateway

    method_provider = 'zynle' if deposit.payment_method == 'ZYNLE_MOMO' else 'lipila'
    active_provider = get_active_payment_provider()
    if method_provider != active_provider:
        deposit.status = 'FAILED'
        deposit.provider_payment_status = 'Failed'
        deposit.failure_reason = 'Payment gateway changed before the deposit was submitted'
        deposit.save(update_fields=['status', 'provider_payment_status', 'failure_reason'])
        return {
            'initialized': True,
            'success': False,
            'payment_url': None,
            'payment_reference': None,
            'order_id': deposit.id,
            'payment_status': 'Failed',
            'message': 'The selected payment method is no longer active. Please try again.',
            'failure_reason': deposit.failure_reason,
        }

    gateway = get_payment_gateway(method_provider)
    result = gateway.initiate_payment(deposit, request, mobile_number=mobile_number)

    if result.success:
        deposit.status = 'PROCESSING'
        deposit.transaction_id = result.provider_transaction_id or result.payment_reference
        deposit.provider_transaction_id = result.provider_transaction_id
        deposit.payment_reference = result.payment_reference
        deposit.payment_provider = result.provider
        deposit.provider_payment_status = result.payment_status or 'Pending'
        deposit.gateway_response = result.raw_response
        deposit.save(
            update_fields=[
                'status',
                'transaction_id',
                'provider_transaction_id',
                'payment_reference',
                'payment_provider',
                'provider_payment_status',
                'gateway_response',
                'idempotency_key',
            ]
        )
        return {
            'initialized': True,
            'success': True,
            'payment_url': result.payment_url,
            'payment_reference': result.payment_reference,
            'order_id': deposit.id,
            'payment_status': result.payment_status,
            'message': result.message,
            'failure_reason': None,
        }

    deposit.status = 'FAILED'
    deposit.provider_payment_status = 'Failed'
    deposit.failure_reason = result.failure_reason or result.message
    deposit.gateway_response = result.raw_response
    deposit.save(
        update_fields=[
            'status',
            'provider_payment_status',
            'failure_reason',
            'gateway_response',
        ]
    )
    return {
        'initialized': True,
        'success': False,
        'payment_url': None,
        'payment_reference': result.payment_reference,
        'order_id': deposit.id,
        'payment_status': 'Failed',
        'message': result.message,
        'failure_reason': deposit.failure_reason,
    }


def initialize_lipila_deposit_payment(deposit, request, mobile_number=None):
    """Backward-compatible alias for older callers."""
    return initialize_deposit_payment(deposit, request, mobile_number=mobile_number)


def get_deposit_payment_status_payload(deposit):
    """Public status for polling — derived from DB only (webhook-updated)."""
    return {
        'order_id': deposit.id,
        'deposit_id': deposit.id,
        'status': deposit.status,
        'payment_provider': deposit.payment_provider,
        'provider_payment_status': deposit.provider_payment_status,
        'payment_reference': deposit.payment_reference,
        'provider_transaction_id': deposit.provider_transaction_id,
        'amount': str(deposit.amount),
        'completed': deposit.status == 'COMPLETED',
        'failed': deposit.status == 'FAILED',
        'pending': deposit.status in ('PENDING', 'PROCESSING'),
    }


@transaction.atomic
def refund_withdrawal_reservation(withdrawal, reason: str = ''):
    """
    Return funds for a withdrawal only if the wallet was actually debited.

    New withdrawals are debited on completion, so pending failures/cancellations
    do not need a credit. The debit lookup keeps this safe for older pending
    withdrawals that were debited when the request was created.
    """
    withdrawal = Withdrawal.objects.select_for_update().get(id=withdrawal.id)
    wallet = Wallet.objects.select_for_update().get(id=withdrawal.wallet_id)
    existing_debit = find_withdrawal_debit(withdrawal)
    if not existing_debit:
        return {
            'refunded': False,
            'transaction_created': False,
            'new_balance': wallet.balance,
            'transaction_id': None,
        }

    description = f"Withdrawal {withdrawal.id} refund"
    if reason:
        description = f"{description} - {reason}"

    existing_refund = Transaction.objects.filter(
        wallet=wallet,
        amount=withdrawal.amount,
        transaction_type='OTHER',
        description__startswith=f"Withdrawal {withdrawal.id} refund",
    ).first()
    if existing_refund:
        return {
            'refunded': False,
            'transaction_created': False,
            'new_balance': wallet.balance,
            'transaction_id': existing_refund.id,
        }

    wallet.balance += withdrawal.amount
    wallet.save(update_fields=['balance'])
    transaction_record = Transaction.objects.create(
        wallet=wallet,
        amount=withdrawal.amount,
        transaction_type='OTHER',
        description=description,
    )
    return {
        'refunded': True,
        'transaction_created': True,
        'new_balance': wallet.balance,
        'transaction_id': transaction_record.id,
    }


@transaction.atomic
def complete_deposit_and_credit_wallet(deposit):
    """
    Securely complete a deposit and credit the wallet balance (admin/manual use).
    Lipila production flow should prefer webhook via apply_deposit_webhook_status.
    """
    try:
        deposit = Deposit.objects.select_for_update().get(id=deposit.id)

        if deposit.status == 'COMPLETED':
            existing_transaction = Transaction.objects.filter(
                wallet=deposit.wallet,
                transaction_type='DEPOSIT',
                description__contains=f"Deposit of ZMW {deposit.amount}",
                created_at__gte=deposit.created_at,
            ).first()
            if existing_transaction:
                return {
                    'success': True,
                    'wallet_credited': True,
                    'transaction_created': False,
                    'message': 'Deposit already completed and wallet credited',
                }

        if deposit.status in ['FAILED', 'CANCELLED']:
            return {
                'success': False,
                'wallet_credited': False,
                'transaction_created': False,
                'message': f'Cannot credit wallet for deposit with status: {deposit.status}',
            }

        wallet = Wallet.objects.select_for_update().get(id=deposit.wallet.id)
        deposit.status = 'COMPLETED'
        deposit.provider_payment_status = 'Successful'
        if not deposit.completed_at:
            deposit.completed_at = timezone.now()
        if not deposit.verification_hash:
            if hasattr(deposit, 'generate_verification_hash'):
                deposit.verification_hash = deposit.generate_verification_hash()
            else:
                import hashlib
                hash_data = (
                    f"{deposit.id}_{deposit.user_id}_{deposit.amount}_"
                    f"{deposit.status}_{deposit.transaction_id}"
                )
                deposit.verification_hash = hashlib.sha256(hash_data.encode()).hexdigest()

        wallet.balance += deposit.amount
        transaction_record = Transaction.objects.create(
            wallet=wallet,
            amount=deposit.amount,
            transaction_type='DEPOSIT',
            description=f"Deposit of ZMW {deposit.amount:.2f} via {deposit.get_payment_method_display()}",
        )
        deposit.save(update_fields=['status', 'completed_at', 'verification_hash', 'provider_payment_status'])
        wallet.save(update_fields=['balance'])

        from audit.utils import log_action
        log_action(
            action='deposit_completed',
            user=deposit.user,
            details={
                'deposit_id': deposit.id,
                'amount': str(deposit.amount),
                'payment_method': deposit.payment_method,
                'transaction_id': deposit.transaction_id,
                'new_balance': str(wallet.balance),
                'transaction_record_id': transaction_record.id,
            },
        )
        return {
            'success': True,
            'wallet_credited': True,
            'transaction_created': True,
            'message': 'Deposit completed and wallet credited successfully',
            'new_balance': wallet.balance,
            'transaction_id': transaction_record.id,
        }
    except Deposit.DoesNotExist:
        return {
            'success': False,
            'wallet_credited': False,
            'transaction_created': False,
            'message': 'Deposit not found',
        }
    except Exception as e:
        logger.error('Error completing deposit %s: %s', deposit.id, e, exc_info=True)
        return {
            'success': False,
            'wallet_credited': False,
            'transaction_created': False,
            'message': f'Error: {str(e)}',
        }


@transaction.atomic
def process_withdrawal_and_debit_wallet(withdrawal, gateway_result: dict | None = None):
    """Securely complete a withdrawal and debit the wallet exactly once."""
    try:
        withdrawal = Withdrawal.objects.select_for_update().get(id=withdrawal.id)
        if withdrawal.status == 'COMPLETED':
            existing_transaction = find_withdrawal_debit(withdrawal)
            if existing_transaction:
                return {
                    'success': True,
                    'wallet_debited': True,
                    'transaction_created': False,
                    'new_balance': withdrawal.wallet.balance,
                    'message': 'Withdrawal already completed and wallet debited',
                }
        if withdrawal.status in ['FAILED', 'CANCELLED']:
            return {
                'success': False,
                'wallet_debited': False,
                'transaction_created': False,
                'new_balance': withdrawal.wallet.balance,
                'message': f'Cannot debit wallet for withdrawal with status: {withdrawal.status}',
            }
        wallet = Wallet.objects.select_for_update().get(id=withdrawal.wallet.id)
        gateway_result = gateway_result or {}
        existing_transaction = find_withdrawal_debit(withdrawal)
        transaction_record = None
        if not existing_transaction:
            if wallet.balance < withdrawal.amount:
                return {
                    'success': False,
                    'wallet_debited': False,
                    'transaction_created': False,
                    'message': 'Insufficient wallet balance to complete withdrawal',
                    'new_balance': wallet.balance,
                    'transaction_id': None,
                }

            wallet.balance -= withdrawal.amount
            wallet.save(update_fields=['balance'])
            transaction_record = Transaction.objects.create(
                wallet=wallet,
                amount=-withdrawal.amount,
                transaction_type='WITHDRAWAL',
                description=(
                    f"Withdrawal of ZMW {withdrawal.amount:.2f} via "
                    f"{withdrawal.get_payment_method_display()}"
                ),
            )

        withdrawal.status = 'COMPLETED'
        txid = gateway_result.get('transaction_id') or gateway_result.get('transfer_code')
        if txid:
            withdrawal.transaction_id = str(txid)
            withdrawal.gateway_transaction_id = str(txid)
        if gateway_result.get('gateway_response') is not None:
            withdrawal.gateway_response = gateway_result.get('gateway_response') or {}
        withdrawal.failure_reason = None
        withdrawal.save(
            update_fields=[
                'status',
                'transaction_id',
                'gateway_transaction_id',
                'gateway_response',
                'failure_reason',
            ]
        )
        return {
            'success': True,
            'wallet_debited': True,
            'transaction_created': transaction_record is not None,
            'message': 'Withdrawal completed and wallet debited',
            'new_balance': wallet.balance,
            'transaction_id': transaction_record.id if transaction_record else existing_transaction.id,
        }
    except Withdrawal.DoesNotExist:
        return {
            'success': False,
            'wallet_debited': False,
            'transaction_created': False,
            'new_balance': None,
            'message': 'Withdrawal not found',
        }
    except Exception as e:
        logger.error('Error processing withdrawal %s: %s', withdrawal.id, e, exc_info=True)
        return {
            'success': False,
            'wallet_debited': False,
            'transaction_created': False,
            'new_balance': None,
            'message': f'Error: {str(e)}',
        }
