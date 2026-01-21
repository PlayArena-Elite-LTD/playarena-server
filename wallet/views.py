from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django_ratelimit.decorators import ratelimit
from django.db import transaction
from decimal import Decimal
import json

from .models import Wallet, Transaction, Deposit, Withdrawal
from .forms import DepositForm, WithdrawalForm

@login_required
def wallet_view(request):
    """View user's wallet balance and transaction history."""
    try:
        wallet = request.user.wallet
        transactions = wallet.transactions.all().order_by('-created_at')[:20]
    except Wallet.DoesNotExist:
        wallet = Wallet.objects.create(user=request.user)
        transactions = []
    
    return render(request, 'wallet/wallet.html', {
        'wallet': wallet,
        'transactions': transactions
    })

@ratelimit(key='user', rate='10/m', block=True)
@login_required
@transaction.atomic
def deposit_view(request):
    """
    Handle deposit requests using Deposit model with status tracking.
    
    GET: Display deposit form
    POST: Process deposit form submission
    Creates a Deposit record with PENDING status. Wallet balance is only
    updated when deposit status changes to COMPLETED (via webhook or admin).
    """
    # Get or create user's wallet
    try:
        wallet = request.user.wallet
    except Wallet.DoesNotExist:
        wallet = Wallet.objects.create(user=request.user)
    
    if request.method == 'POST':
        form = DepositForm(request.POST, user=request.user)
        if form.is_valid():
            try:
                amount = form.cleaned_data['amount']
                payment_method = form.cleaned_data['payment_method']
                
                # Create Deposit instance (validation happens in clean())
                deposit = Deposit(
                    user=request.user,
                    amount=amount,
                    payment_method=payment_method,
                    status='PENDING',  # Start as PENDING
                    wallet=wallet
                )
                
                # Run validation (checks amount limits, etc.)
                deposit.full_clean()
                deposit.save()
                
                messages.success(request, f'Deposit request of ${amount:.2f} created successfully. Processing...')
                return redirect('wallet')
            except Exception as e:
                # Handle validation errors from Deposit model
                error_message = str(e)
                if hasattr(e, 'message_dict'):
                    # Django ValidationError
                    errors = e.message_dict
                    error_message = ', '.join([f"{field}: {', '.join(msg_list)}" for field, msg_list in errors.items()])
                
                messages.error(request, f'Deposit request failed: {error_message}')
        else:
            # Form validation errors
            messages.error(request, 'Please correct the errors below.')
    else:
        # GET request - display form
        form = DepositForm(user=request.user)
    
    return render(request, 'wallet/deposit.html', {
        'form': form,
        'wallet': wallet
    })

@ratelimit(key='user', rate='5/m', block=True)
@login_required
@transaction.atomic
def withdraw_view(request):
    """
    Handle withdrawal requests using Withdrawal model with status tracking.
    
    GET: Display withdrawal form
    POST: Process withdrawal form submission
    Creates a Withdrawal record with PENDING status. Wallet balance is only
    updated when withdrawal status changes to COMPLETED (via webhook or admin).
    """
    # Get or create user's wallet
    try:
        wallet = request.user.wallet
    except Wallet.DoesNotExist:
        wallet = Wallet.objects.create(user=request.user)
    
    if request.method == 'POST':
        form = WithdrawalForm(request.POST, user=request.user)
        if form.is_valid():
            try:
                amount = form.cleaned_data['amount']
                payment_method = form.cleaned_data['payment_method']
                account_details = form.cleaned_data['account_details']
                
                # Create Withdrawal instance (validation happens in clean())
                withdrawal = Withdrawal(
                    user=request.user,
                    amount=amount,
                    payment_method=payment_method,
                    account_details=account_details,
                    status='PENDING',  # Start as PENDING
                    wallet=wallet
                )
                
                # Run validation (checks amount limits, balance, etc.)
                withdrawal.full_clean()
                withdrawal.save()
                
                messages.success(request, f'Withdrawal request of ${amount:.2f} created successfully. Processing...')
                return redirect('wallet')
            except Exception as e:
                # Handle validation errors from Withdrawal model
                error_message = str(e)
                if hasattr(e, 'message_dict'):
                    # Django ValidationError
                    errors = e.message_dict
                    error_message = ', '.join([f"{field}: {', '.join(msg_list)}" for field, msg_list in errors.items()])
                
                messages.error(request, f'Withdrawal request failed: {error_message}')
        else:
            # Form validation errors
            messages.error(request, 'Please correct the errors below.')
    else:
        # GET request - display form
        form = WithdrawalForm(user=request.user)
    
    return render(request, 'wallet/withdraw.html', {
        'form': form,
        'wallet': wallet
    })

@login_required
def transaction_history(request):
    """View detailed transaction history."""
    try:
        wallet = request.user.wallet
        transactions = wallet.transactions.all().order_by('-created_at')
    except Wallet.DoesNotExist:
        transactions = []
    
    return render(request, 'wallet/transactions.html', {
        'transactions': transactions
    })
