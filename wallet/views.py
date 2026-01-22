from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods
from django_ratelimit.decorators import ratelimit
from decimal import Decimal, InvalidOperation
import logging
from core.ratelimit_helpers import rate_limit_response

from .models import Wallet, Transaction
from .forms import DepositForm, WithdrawalForm

logger = logging.getLogger('django_ratelimit')


@login_required
@ratelimit(key='user', rate='30/m', method='GET', block=True, fn=rate_limit_response)
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
@ratelimit(key='user', rate='10/m', method='POST', block=True, fn=rate_limit_response)
def deposit(request):
    """Deposit funds - 10 per minute per user"""
    if request.method == 'POST':
        form = DepositForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    amount = form.cleaned_data['amount']
                    payment_method = form.cleaned_data['payment_method']
                    
                    wallet = request.user.wallet
                    wallet.balance += amount
                    wallet.save()
                    
                    # Record transaction
                    Transaction.objects.create(
                        wallet=wallet,
                        amount=amount,
                        transaction_type='DEPOSIT',
                        description=f"Deposit of ${amount} via {payment_method}"
                    )
                    
                    logger.info(f"Deposit of ${amount} processed for user {request.user.username} via {payment_method}")
                    messages.success(request, f"Successfully deposited ${amount}. Your new balance is ${wallet.balance}.")
                    
                    # Handle JSON requests
                    if request.headers.get('Content-Type', '').startswith('application/json') or \
                       request.headers.get('Accept', '').startswith('application/json'):
                        return JsonResponse({
                            'status': 'success',
                            'amount': float(amount),
                            'new_balance': float(wallet.balance),
                            'message': f'Successfully deposited ${amount}'
                        })
                    
                    return redirect('wallet')
            except Exception as e:
                logger.error(f"Error processing deposit for user {request.user.username}: {str(e)}")
                messages.error(request, "An error occurred while processing your deposit.")
                if request.headers.get('Content-Type', '').startswith('application/json') or \
                   request.headers.get('Accept', '').startswith('application/json'):
                    return JsonResponse({
                        'status': 'error',
                        'message': 'An error occurred while processing your deposit.'
                    }, status=500)
    else:
        form = DepositForm()
    
    context = {
        'form': form,
        'wallet': request.user.wallet,
    }
    return render(request, 'wallet/deposit.html', context)


@login_required
@ratelimit(key='user', rate='5/h', method='POST', block=True, fn=rate_limit_response)
def withdraw(request):
    """Withdraw funds - 5 per hour per user"""
    wallet = request.user.wallet
    
    if request.method == 'POST':
        form = WithdrawalForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    amount = form.cleaned_data['amount']
                    payment_method = form.cleaned_data['payment_method']
                    account_details = form.cleaned_data['account_details']
                    
                    # Check balance
                    if wallet.balance < amount:
                        form.add_error('amount', f"Insufficient funds. Your balance is ${wallet.balance}.")
                        context = {
                            'form': form,
                            'wallet': wallet,
                        }
                        return render(request, 'wallet/withdraw.html', context)
                    
                    # Process withdrawal
                    wallet.balance -= amount
                    wallet.save()
                    
                    # Record transaction
                    Transaction.objects.create(
                        wallet=wallet,
                        amount=-amount,
                        transaction_type='WITHDRAWAL',
                        description=f"Withdrawal of ${amount} via {payment_method} to {account_details[:50]}"
                    )
                    
                    logger.info(f"Withdrawal of ${amount} processed for user {request.user.username} via {payment_method}")
                    messages.success(request, f"Successfully withdrew ${amount}. Your new balance is ${wallet.balance}.")
                    
                    # Handle JSON requests
                    if request.headers.get('Content-Type', '').startswith('application/json') or \
                       request.headers.get('Accept', '').startswith('application/json'):
                        return JsonResponse({
                            'status': 'success',
                            'amount': float(amount),
                            'new_balance': float(wallet.balance),
                            'message': f'Successfully withdrew ${amount}'
                        })
                    
                    return redirect('wallet')
            except Exception as e:
                logger.error(f"Error processing withdrawal for user {request.user.username}: {str(e)}")
                messages.error(request, "An error occurred while processing your withdrawal.")
                if request.headers.get('Content-Type', '').startswith('application/json') or \
                   request.headers.get('Accept', '').startswith('application/json'):
                    return JsonResponse({
                        'status': 'error',
                        'message': 'An error occurred while processing your withdrawal.'
                    }, status=500)
    else:
        form = WithdrawalForm()
    
    context = {
        'form': form,
        'wallet': wallet,
    }
    return render(request, 'wallet/withdraw.html', context)


@login_required
def wallet_view(request):
    """Main wallet view showing balance and transaction history"""
    wallet = request.user.wallet
    transactions = wallet.transactions.all().order_by('-created_at')[:50]  # Last 50 transactions
    
    context = {
        'wallet': wallet,
        'transactions': transactions,
    }
    
    return render(request, 'wallet/wallet.html', context)
