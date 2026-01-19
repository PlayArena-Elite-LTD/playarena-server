from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django_ratelimit.decorators import ratelimit
from decimal import Decimal
import json

from .models import Wallet, Transaction

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
def deposit_view(request):
    """Handle deposit requests."""
    try:
        data = json.loads(request.body)
        amount = Decimal(str(data.get('amount', '0')))
        
        if amount <= 0:
            return JsonResponse({'success': False, 'error': 'Amount must be positive'})
        
        wallet = request.user.wallet
        wallet.balance += amount
        wallet.save()
        
        # Create transaction record
        Transaction.objects.create(
            wallet=wallet,
            amount=amount,
            transaction_type='DEPOSIT',
            description=f'Deposit of ${amount}'
        )
        
        return JsonResponse({'success': True, 'new_balance': str(wallet.balance)})
        
    except (ValueError, json.JSONDecodeError):
        return JsonResponse({'success': False, 'error': 'Invalid request'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': 'Deposit failed'})

@ratelimit(key='user', rate='5/m', block=True)
@login_required
@require_POST
def withdraw_view(request):
    """Handle withdrawal requests."""
    try:
        data = json.loads(request.body)
        amount = Decimal(str(data.get('amount', '0')))
        
        if amount <= 0:
            return JsonResponse({'success': False, 'error': 'Amount must be positive'})
        
        wallet = request.user.wallet
        
        if wallet.balance < amount:
            return JsonResponse({'success': False, 'error': 'Insufficient balance'})
        
        wallet.balance -= amount
        wallet.save()
        
        # Create transaction record
        Transaction.objects.create(
            wallet=wallet,
            amount=-amount,
            transaction_type='WITHDRAWAL',
            description=f'Withdrawal of ${amount}'
        )
        
        return JsonResponse({'success': True, 'new_balance': str(wallet.balance)})
        
    except (ValueError, json.JSONDecodeError):
        return JsonResponse({'success': False, 'error': 'Invalid request'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': 'Withdrawal failed'})

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
