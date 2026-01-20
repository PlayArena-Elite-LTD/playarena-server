"""
Utility functions for wallet transaction reconciliation and auditing.
"""
from decimal import Decimal
from django.db.models import Sum, Q
from django.utils import timezone
from datetime import timedelta

from .models import Wallet, Transaction, Deposit, Withdrawal


def detect_all_discrepancies():
    """
    Security: Detect all wallets with balance discrepancies.
    
    Returns:
        list: List of dictionaries with discrepancy details
    """
    discrepancies = []
    
    for wallet in Wallet.objects.all():
        result = wallet.verify_balance_integrity()
        if not result['is_valid']:
            discrepancies.append({
                'wallet_id': wallet.id,
                'user_id': wallet.user.id if wallet.user else None,
                'username': wallet.user.username if wallet.user else 'Unknown',
                'expected_balance': result['expected_balance'],
                'actual_balance': result['actual_balance'],
                'discrepancy': result['discrepancy'],
                'transaction_count': result['transaction_count'],
            })
    
    return discrepancies


def reconcile_wallet(wallet_id):
    """
    Security: Reconcile a specific wallet by recalculating balance.
    
    Args:
        wallet_id: The ID of the wallet to reconcile
    
    Returns:
        dict: Result of reconciliation
    """
    try:
        wallet = Wallet.objects.get(id=wallet_id)
        before_balance = wallet.balance
        result_before = wallet.verify_balance_integrity()
        
        new_balance = wallet.recalculate_balance()
        
        wallet.refresh_from_db()
        result_after = wallet.verify_balance_integrity()
        
        return {
            'success': True,
            'wallet_id': wallet_id,
            'before_balance': before_balance,
            'after_balance': new_balance,
            'was_valid_before': result_before['is_valid'],
            'is_valid_after': result_after['is_valid'],
            'discrepancy_fixed': result_before['discrepancy'],
        }
    except Wallet.DoesNotExist:
        return {
            'success': False,
            'error': f'Wallet with id {wallet_id} does not exist',
        }


def get_reconciliation_report(start_date=None, end_date=None):
    """
    Security: Generate a reconciliation report for wallets and transactions.
    
    Args:
        start_date: Optional start date for filtering transactions
        end_date: Optional end date for filtering transactions
    
    Returns:
        dict: Comprehensive reconciliation report
    """
    # Get all discrepancies
    discrepancies = detect_all_discrepancies()
    
    # Get transaction statistics
    transaction_query = Transaction.objects.all()
    if start_date:
        transaction_query = transaction_query.filter(created_at__gte=start_date)
    if end_date:
        transaction_query = transaction_query.filter(created_at__lte=end_date)
    
    total_transactions = transaction_query.count()
    transaction_sum = transaction_query.aggregate(
        total=Sum('amount')
    )['total'] or Decimal('0.00')
    
    # Get deposit/withdrawal statistics
    deposit_query = Deposit.objects.all()
    withdrawal_query = Withdrawal.objects.all()
    
    if start_date:
        deposit_query = deposit_query.filter(created_at__gte=start_date)
        withdrawal_query = withdrawal_query.filter(created_at__gte=start_date)
    if end_date:
        deposit_query = deposit_query.filter(created_at__lte=end_date)
        withdrawal_query = withdrawal_query.filter(created_at__lte=end_date)
    
    total_deposits = deposit_query.count()
    total_deposit_amount = deposit_query.aggregate(
        total=Sum('amount')
    )['total'] or Decimal('0.00')
    
    total_withdrawals = withdrawal_query.count()
    total_withdrawal_amount = withdrawal_query.aggregate(
        total=Sum('amount')
    )['total'] or Decimal('0.00')
    
    # Calculate total wallet balances
    total_wallet_balance = Wallet.objects.aggregate(
        total=Sum('balance')
    )['total'] or Decimal('0.00')
    
    return {
        'report_date': timezone.now(),
        'period': {
            'start_date': start_date,
            'end_date': end_date,
        },
        'wallets': {
            'total': Wallet.objects.count(),
            'with_discrepancies': len(discrepancies),
            'total_balance': total_wallet_balance,
            'discrepancies': discrepancies,
        },
        'transactions': {
            'total_count': total_transactions,
            'total_amount': transaction_sum,
        },
        'deposits': {
            'total_count': total_deposits,
            'total_amount': total_deposit_amount,
        },
        'withdrawals': {
            'total_count': total_withdrawals,
            'total_amount': total_withdrawal_amount,
        },
    }
