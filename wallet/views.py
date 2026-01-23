from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods
from django_ratelimit.decorators import ratelimit
from decimal import Decimal, InvalidOperation
import logging

from .models import Wallet, Transaction, Deposit, Withdrawal
from .forms import DepositForm, WithdrawalForm

logger = logging.getLogger('django_ratelimit')


@login_required
@ratelimit(key='user', rate='30/m', method='GET', block=True)
def check_balance(request):
    """Check wallet balance - 30 per minute per user"""
    try:
        wallet = request.user.wallet
        balance = wallet.balance
        
        if request.headers.get('Content-Type', '').startswith('application/json') or \
           request.headers.get('Accept', '').startswith('application/json'):
            return JsonResponse({
                'balance': float(balance),
                'status': 'success'
            })
        
        return render(request, 'wallet/balance.html', {'balance': balance})
    except Exception as e:
        logger.error(f"Error checking balance for user {request.user.username}: {str(e)}")
        messages.error(request, "An error occurred while checking your balance.")
        return redirect('dashboard')


@login_required
@ratelimit(key='user', rate='10/m', method='POST', block=True)
def deposit(request):
    """Create deposit request - 10 per minute per user. Creates PENDING deposit."""
    wallet = request.user.wallet
    
    if request.method == 'POST':
        form = DepositForm(request.POST, user=request.user)
        if form.is_valid():
            try:
                with transaction.atomic():
                    amount = form.cleaned_data['amount']
                    payment_method = form.cleaned_data['payment_method']
                    
                    # Create Deposit instance with PENDING status (wallet balance not updated yet)
                    deposit = Deposit(
                        user=request.user,
                        amount=amount,
                        payment_method=payment_method,
                        status='PENDING',
                        wallet=wallet
                    )
                    deposit.full_clean()
                    deposit.save()
                    
                    logger.info(f"Deposit request of ${amount} created for user {request.user.username} via {payment_method}")
                    messages.success(request, f'Deposit request of ${amount:.2f} created successfully. It will be processed shortly.')
                    
                    # Handle JSON requests
                    if request.headers.get('Content-Type', '').startswith('application/json') or \
                       request.headers.get('Accept', '').startswith('application/json'):
                        return JsonResponse({
                            'status': 'success',
                            'deposit_id': deposit.id,
                            'amount': float(amount),
                            'message': f'Deposit request created. Status: {deposit.get_status_display()}'
                        })
                    
                    return redirect('wallet')
            except Exception as e:
                logger.error(f"Error creating deposit for user {request.user.username}: {str(e)}")
                error_msg = str(e)
                if hasattr(e, 'message_dict'):
                    error_msg = ', '.join([f"{k}: {', '.join(v)}" for k, v in e.message_dict.items()])
                messages.error(request, f"Deposit request failed: {error_msg}")
                if request.headers.get('Content-Type', '').startswith('application/json') or \
                   request.headers.get('Accept', '').startswith('application/json'):
                    return JsonResponse({
                        'status': 'error',
                        'message': error_msg
                    }, status=400)
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = DepositForm(user=request.user)
    
    context = {
        'form': form,
        'wallet': wallet,
    }
    return render(request, 'wallet/deposit.html', context)


@login_required
@ratelimit(key='user', rate='5/m', method='POST', block=True)
def withdraw(request):
    """Create withdrawal request - 5 per minute per user. Creates PENDING withdrawal."""
    wallet = request.user.wallet
    
    if request.method == 'POST':
        form = WithdrawalForm(request.POST, user=request.user)
        if form.is_valid():
            try:
                with transaction.atomic():
                    amount = form.cleaned_data['amount']
                    payment_method = form.cleaned_data['payment_method']
                    account_details = form.cleaned_data['account_details']
                    
                    # Create Withdrawal instance with PENDING status (wallet balance not updated yet)
                    withdrawal = Withdrawal(
                        user=request.user,
                        amount=amount,
                        payment_method=payment_method,
                        account_details=account_details,
                        status='PENDING',
                        wallet=wallet
                    )
                    withdrawal.full_clean()  # This validates balance, amount, account_details
                    withdrawal.save()
                    
                    logger.info(f"Withdrawal request of ${amount} created for user {request.user.username} via {payment_method}")
                    messages.success(request, f'Withdrawal request of ${amount:.2f} created successfully. It will be processed shortly.')
                    
                    # Handle JSON requests
                    if request.headers.get('Content-Type', '').startswith('application/json') or \
                       request.headers.get('Accept', '').startswith('application/json'):
                        return JsonResponse({
                            'status': 'success',
                            'withdrawal_id': withdrawal.id,
                            'amount': float(amount),
                            'message': f'Withdrawal request created. Status: {withdrawal.get_status_display()}'
                        })
                    
                    return redirect('wallet')
            except Exception as e:
                logger.error(f"Error creating withdrawal for user {request.user.username}: {str(e)}")
                error_msg = str(e)
                if hasattr(e, 'message_dict'):
                    error_msg = ', '.join([f"{k}: {', '.join(v)}" for k, v in e.message_dict.items()])
                messages.error(request, f"Withdrawal request failed: {error_msg}")
                if request.headers.get('Content-Type', '').startswith('application/json') or \
                   request.headers.get('Accept', '').startswith('application/json'):
                    return JsonResponse({
                        'status': 'error',
                        'message': error_msg
                    }, status=400)
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = WithdrawalForm(user=request.user)
    
    context = {
        'form': form,
        'wallet': wallet,
    }
    return render(request, 'wallet/withdraw.html', context)


@login_required
def wallet_view(request):
    """Main wallet view showing balance and transaction history"""
    wallet = request.user.wallet
    transactions = wallet.transactions.all().order_by('-created_at')[:15]  # Last 15 transactions
    deposits = wallet.deposits.all().order_by('-created_at')[:5]  # Recent deposits
    withdrawals = wallet.withdrawals.all().order_by('-created_at')[:5]  # Recent withdrawals
    
    context = {
        'wallet': wallet,
        'transactions': transactions,
        'deposits': deposits,
        'withdrawals': withdrawals,
    }
    
    return render(request, 'wallet/wallet.html', context)


@login_required
def transaction_history(request):
    """View full transaction history"""
    wallet = request.user.wallet
    transactions = wallet.transactions.all().order_by('-created_at')
    
    context = {
        'wallet': wallet,
        'transactions': transactions,
    }
    
    return render(request, 'wallet/transactions.html', context)
