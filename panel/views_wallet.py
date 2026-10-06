from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from accounts.decorators import support_staff_required
from wallet.models import Wallet, Transaction, Deposit, Withdrawal
from wallet.utils import (
    get_withdrawal_wallet,
    process_withdrawal_and_debit_wallet,
    refund_withdrawal_reservation,
)
from audit.utils import log_action


@support_staff_required
def transaction_list(request):
    q = request.GET.get('q', '').strip()
    txn_type = request.GET.get('type', '')

    transactions = Transaction.objects.select_related('wallet__user').order_by('-created_at')
    if q:
        transactions = transactions.filter(wallet__user__username__icontains=q)
    if txn_type:
        transactions = transactions.filter(transaction_type=txn_type)

    paginator = Paginator(transactions, 50)
    page_obj = paginator.get_page(request.GET.get('page'))

    context = {
        'page_obj': page_obj,
        'q': q,
        'txn_type': txn_type,
        'transaction_types': Transaction.TRANSACTION_TYPES,
    }
    return render(request, 'panel/wallet_transactions.html', context)


@support_staff_required
def wallet_list(request):
    q = request.GET.get('q', '').strip()

    wallets = Wallet.objects.select_related('user').order_by('user__username')
    if q:
        wallets = wallets.filter(Q(user__username__icontains=q) | Q(user__email__icontains=q))

    paginator = Paginator(wallets, 25)
    page_obj = paginator.get_page(request.GET.get('page'))

    context = {'page_obj': page_obj, 'q': q}
    return render(request, 'panel/wallet_wallets.html', context)


@support_staff_required
def wallet_reconcile(request, wallet_id):
    """Reconcile a single wallet's balance against its transaction sum."""
    wallet = get_object_or_404(Wallet, id=wallet_id)
    result = wallet.verify_balance_integrity()
    if result['is_valid']:
        messages.info(request, f"Wallet for {wallet.user.username} is already balanced.")
    else:
        wallet.recalculate_balance()
        messages.success(
            request,
            f"Wallet for {wallet.user.username} reconciled. "
            f"Balance corrected from ${result['actual_balance']} to ${result['expected_balance']}."
        )
    return redirect('wallet_list')


@support_staff_required
def deposit_list(request):
    status = request.GET.get('status', '')
    q = request.GET.get('q', '').strip()

    deposits = Deposit.objects.select_related('user').order_by('-created_at')
    if status:
        deposits = deposits.filter(status=status)
    if q:
        deposits = deposits.filter(user__username__icontains=q)

    paginator = Paginator(deposits, 25)
    page_obj = paginator.get_page(request.GET.get('page'))

    context = {
        'page_obj': page_obj,
        'status': status,
        'q': q,
        'status_choices': Deposit.STATUS_CHOICES,
    }
    return render(request, 'panel/wallet_deposits.html', context)


@support_staff_required
@transaction.atomic
def deposit_mark_completed(request, deposit_id):
    """Mark a deposit as COMPLETED and credit the wallet. Mirrors wallet.admin.DepositAdmin.mark_as_completed."""
    deposit = get_object_or_404(Deposit, id=deposit_id)
    if deposit.status == 'COMPLETED':
        messages.info(request, "Deposit is already completed.")
        return redirect('deposit_list')
    if deposit.status in ['FAILED', 'CANCELLED']:
        messages.error(request, "Cannot complete a deposit that is failed or cancelled.")
        return redirect('deposit_list')

    from wallet.utils import credit_deposit_wallet

    wallet, _transaction = credit_deposit_wallet(deposit)
    Deposit.objects.filter(id=deposit.id).update(status='COMPLETED', updated_at=timezone.now())

    log_action(
        action='deposit_completed',
        user=request.user,
        details={
            'deposit_id': deposit.id,
            'amount': str(deposit.amount),
            'payment_method': deposit.payment_method,
            'completed_by': 'panel',
            'new_balance': str(wallet.balance),
        },
        request=request,
    )
    messages.success(request, f"Deposit #{deposit.id} marked as completed.")
    return redirect('deposit_list')


@support_staff_required
def deposit_mark_failed(request, deposit_id):
    deposit = get_object_or_404(Deposit, id=deposit_id)
    if deposit.status not in ['PENDING', 'PROCESSING']:
        messages.error(request, "Only pending/processing deposits can be marked as failed.")
        return redirect('deposit_list')

    Deposit.objects.filter(id=deposit.id).update(status='FAILED', updated_at=timezone.now())
    log_action(
        action='deposit_failed',
        user=request.user,
        details={
            'deposit_id': deposit.id,
            'amount': str(deposit.amount),
            'payment_method': deposit.payment_method,
            'failed_by': 'panel',
        },
        request=request,
    )
    messages.success(request, f"Deposit #{deposit.id} marked as failed.")
    return redirect('deposit_list')


@support_staff_required
def deposit_mark_cancelled(request, deposit_id):
    deposit = get_object_or_404(Deposit, id=deposit_id)
    if deposit.status not in ['PENDING', 'PROCESSING']:
        messages.error(request, "Only pending/processing deposits can be cancelled.")
        return redirect('deposit_list')

    Deposit.objects.filter(id=deposit.id).update(status='CANCELLED', updated_at=timezone.now())
    log_action(
        action='deposit_cancelled',
        user=request.user,
        details={
            'deposit_id': deposit.id,
            'amount': str(deposit.amount),
            'payment_method': deposit.payment_method,
            'cancelled_by': 'panel',
        },
        request=request,
    )
    messages.success(request, f"Deposit #{deposit.id} marked as cancelled.")
    return redirect('deposit_list')


@support_staff_required
def withdrawal_list(request):
    status = request.GET.get('status', '')
    q = request.GET.get('q', '').strip()

    withdrawals = Withdrawal.objects.select_related('user').order_by('-created_at')
    if status:
        withdrawals = withdrawals.filter(status=status)
    if q:
        withdrawals = withdrawals.filter(user__username__icontains=q)

    paginator = Paginator(withdrawals, 25)
    page_obj = paginator.get_page(request.GET.get('page'))

    context = {
        'page_obj': page_obj,
        'status': status,
        'q': q,
        'status_choices': Withdrawal.STATUS_CHOICES,
    }
    return render(request, 'panel/wallet_withdrawals.html', context)


@support_staff_required
@transaction.atomic
def withdrawal_mark_completed(request, withdrawal_id):
    """Mark a withdrawal as COMPLETED and debit the wallet (no gateway call)."""
    withdrawal = get_object_or_404(Withdrawal, id=withdrawal_id)
    if withdrawal.status == 'COMPLETED':
        messages.info(request, "Withdrawal is already completed.")
        return redirect('withdrawal_list')
    if withdrawal.status in ['FAILED', 'CANCELLED']:
        messages.error(request, "Cannot complete a withdrawal that is failed or cancelled.")
        return redirect('withdrawal_list')

    completion = process_withdrawal_and_debit_wallet(withdrawal)
    if not completion.get('success'):
        messages.error(request, f"Could not complete withdrawal: {completion.get('message')}")
        return redirect('withdrawal_list')

    withdrawal.refresh_from_db()
    log_action(
        action='withdrawal_completed',
        user=request.user,
        details={
            'withdrawal_id': withdrawal.id,
            'amount': str(withdrawal.amount),
            'payment_method': withdrawal.payment_method,
            'completed_by': 'panel',
            'new_balance': str(get_withdrawal_wallet(withdrawal).balance),
        },
        request=request,
    )
    messages.success(request, f"Withdrawal #{withdrawal.id} marked as completed.")
    return redirect('withdrawal_list')


@support_staff_required
@transaction.atomic
def withdrawal_mark_failed(request, withdrawal_id):
    withdrawal = get_object_or_404(Withdrawal, id=withdrawal_id)
    if withdrawal.status not in ['PENDING', 'PROCESSING']:
        messages.error(request, "Only pending/processing withdrawals can be marked as failed.")
        return redirect('withdrawal_list')

    Withdrawal.objects.filter(id=withdrawal.id).update(status='FAILED', updated_at=timezone.now())
    refund_result = refund_withdrawal_reservation(withdrawal, 'Withdrawal failed by admin (panel)')
    log_action(
        action='withdrawal_failed',
        user=request.user,
        details={
            'withdrawal_id': withdrawal.id,
            'amount': str(withdrawal.amount),
            'payment_method': withdrawal.payment_method,
            'failed_by': 'panel',
            'refunded': refund_result['refunded'],
            'new_balance': str(refund_result['new_balance']),
        },
        request=request,
    )
    messages.success(request, f"Withdrawal #{withdrawal.id} marked as failed.")
    return redirect('withdrawal_list')


@support_staff_required
@transaction.atomic
def withdrawal_mark_cancelled(request, withdrawal_id):
    withdrawal = get_object_or_404(Withdrawal, id=withdrawal_id)
    if withdrawal.status not in ['PENDING', 'PROCESSING']:
        messages.error(request, "Only pending/processing withdrawals can be cancelled.")
        return redirect('withdrawal_list')

    Withdrawal.objects.filter(id=withdrawal.id).update(status='CANCELLED', updated_at=timezone.now())
    refund_result = refund_withdrawal_reservation(withdrawal, 'Withdrawal cancelled by admin (panel)')
    log_action(
        action='withdrawal_cancelled',
        user=request.user,
        details={
            'withdrawal_id': withdrawal.id,
            'amount': str(withdrawal.amount),
            'payment_method': withdrawal.payment_method,
            'cancelled_by': 'panel',
            'refunded': refund_result['refunded'],
            'new_balance': str(refund_result['new_balance']),
        },
        request=request,
    )
    messages.success(request, f"Withdrawal #{withdrawal.id} marked as cancelled.")
    return redirect('withdrawal_list')
