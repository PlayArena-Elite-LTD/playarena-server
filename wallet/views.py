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
@require_POST
@transaction.atomic
def deposit_view(request):
    """
    Handle deposit requests using Deposit model with status tracking.
    
    Creates a Deposit record with PENDING status. Wallet balance is only
    updated when deposit status changes to COMPLETED (via webhook or admin).
    """
    try:
        data = json.loads(request.body)
        amount = Decimal(str(data.get('amount', '0')))
        payment_method = data.get('payment_method', 'OTHER')  # Default to OTHER if not specified
        
        # Validate payment method
        valid_methods = [choice[0] for choice in Deposit.PAYMENT_METHOD_CHOICES]
        if payment_method not in valid_methods:
            payment_method = 'OTHER'
        
        # Get user's wallet
        wallet = request.user.wallet
        
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
        
        # Return success with deposit ID and status
        return JsonResponse({
            'success': True,
            'deposit_id': deposit.id,
            'status': deposit.status,
            'amount': str(deposit.amount),
            'message': 'Deposit request created. Processing...',
            'current_balance': str(wallet.balance)  # Balance unchanged until COMPLETED
        })
        
    except (ValueError, json.JSONDecodeError) as e:
        return JsonResponse({'success': False, 'error': 'Invalid request data'})
    except Exception as e:
        # Handle validation errors from Deposit model
        error_message = str(e)
        if hasattr(e, 'message_dict'):
            # Django ValidationError
            errors = e.message_dict
            error_message = ', '.join([f"{field}: {', '.join(messages)}" for field, messages in errors.items()])
        
        return JsonResponse({
            'success': False,
            'error': error_message or 'Deposit request failed'
        })

@ratelimit(key='user', rate='5/m', block=True)
@login_required
@require_POST
@transaction.atomic
def withdraw_view(request):
    """
    Handle withdrawal requests using Withdrawal model with status tracking.
    
    Creates a Withdrawal record with PENDING status. Wallet balance is only
    updated when withdrawal status changes to COMPLETED (via webhook or admin).
    """
    try:
        data = json.loads(request.body)
        amount = Decimal(str(data.get('amount', '0')))
        payment_method = data.get('payment_method', 'BANK_TRANSFER')  # Default to BANK_TRANSFER
        account_details = data.get('account_details', '')
        
        # Validate payment method
        valid_methods = [choice[0] for choice in Withdrawal.PAYMENT_METHOD_CHOICES]
        if payment_method not in valid_methods:
            payment_method = 'BANK_TRANSFER'
        
        # Validate account details (required for withdrawal)
        if not account_details or not account_details.strip():
            return JsonResponse({
                'success': False,
                'error': 'Account details are required for withdrawal'
            })
        
        # Get user's wallet
        wallet = request.user.wallet
        
        # Create Withdrawal instance (validation happens in clean())
        withdrawal = Withdrawal(
            user=request.user,
            amount=amount,
            payment_method=payment_method,
            account_details=account_details.strip(),
            status='PENDING',  # Start as PENDING
            wallet=wallet
        )
        
        # Run validation (checks amount limits, balance, etc.)
        withdrawal.full_clean()
        withdrawal.save()
        
        # Return success with withdrawal ID and status
        return JsonResponse({
            'success': True,
            'withdrawal_id': withdrawal.id,
            'status': withdrawal.status,
            'amount': str(withdrawal.amount),
            'message': 'Withdrawal request created. Processing...',
            'current_balance': str(wallet.balance)  # Balance unchanged until COMPLETED
        })
        
    except (ValueError, json.JSONDecodeError) as e:
        return JsonResponse({'success': False, 'error': 'Invalid request data'})
    except Exception as e:
        # Handle validation errors from Withdrawal model
        error_message = str(e)
        if hasattr(e, 'message_dict'):
            # Django ValidationError
            errors = e.message_dict
            error_message = ', '.join([f"{field}: {', '.join(messages)}" for field, messages in errors.items()])
        
        return JsonResponse({
            'success': False,
            'error': error_message or 'Withdrawal request failed'
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
