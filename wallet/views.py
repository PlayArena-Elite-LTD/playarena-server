from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from core.ratelimit import ratelimit
from django.db import transaction
from django.conf import settings
from decimal import Decimal
import json
import logging
import time
from urllib.parse import urljoin

from .models import Wallet, Transaction, Deposit, Withdrawal, SavedPaymentMethod
from .forms import DepositForm, WithdrawalForm
from .payment_method_forms import SavedPaymentMethodForm, DeletePaymentMethodForm
from wallet.payment_debug import payment_debug_enabled, mask_secret

logger = logging.getLogger(__name__)


def _get_rate_limit_key(request):
    """
    Get rate limit key: use user ID if authenticated, otherwise use IP.
    This ensures rate limiting works correctly even when @ratelimit is outermost.
    Returns just the identifier (user ID or IP) - django-ratelimit adds its own prefix.
    """
    if hasattr(request, 'user') and request.user.is_authenticated:
        return str(request.user.id)
    return request.META.get('REMOTE_ADDR', 'unknown')


def _build_public_url(request, path_or_url: str) -> str:
    """
    Build an absolute URL for external services (e.g. Pesapal callback/IPN).

    If `settings.PUBLIC_BASE_URL` is set, we join it with the provided path.
    Otherwise we fall back to `request.build_absolute_uri(...)`.
    """
    if hasattr(settings, 'PUBLIC_BASE_URL') and settings.PUBLIC_BASE_URL:
        return urljoin(settings.PUBLIC_BASE_URL, path_or_url)
    return request.build_absolute_uri(path_or_url)


@login_required
def wallet_view(request):
    """Display user's wallet with balance and recent transactions"""
    try:
        wallet = request.user.wallet
        transactions = wallet.transactions.all().order_by('-created_at')[:50]  # Last 50 transactions
        
        context = {
            'wallet': wallet,
            'transactions': transactions,
        }
        
        return render(request, 'wallet/wallet.html', context)
    except Wallet.DoesNotExist:
        # Create wallet if it doesn't exist
        wallet = Wallet.objects.create(user=request.user)
        return render(request, 'wallet/wallet.html', {'wallet': wallet, 'transactions': []})


@ratelimit(key=_get_rate_limit_key, rate='10/m', method='POST', block=True)
@login_required
@require_POST
@transaction.atomic
def deposit_view(request):
    """
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
                t0 = time.perf_counter()
                amount = form.cleaned_data['amount']
                payment_method = form.cleaned_data['payment_method']

                if payment_debug_enabled():
                    logger.info(
                        "[PAYMENT_DEBUG] deposit_submit: user=%s amount=%s method=%s",
                        request.user.username,
                        str(amount),
                        payment_method,
                    )
                
                # Create Deposit instance (validation happens in clean())
                deposit = Deposit(
                    user=request.user,
                    amount=amount,
                    payment_method=payment_method,
                    status='PENDING',  # Start as PENDING
                    wallet=wallet
                )
                
                deposit.save()
                
                t1 = time.perf_counter()
                if payment_debug_enabled():
                    logger.info(
                        "[PAYMENT_DEBUG] deposit_created: user=%s deposit_id=%s amount=%s time=%.3fs",
                        request.user.username,
                        deposit.id,
                        str(amount),
                        t1 - t0,
                    )
                
                messages.success(request, f'Deposit request for ${amount} submitted successfully!')
                return redirect('wallet')
                
            except Exception as e:
                logger.error(f"Deposit error for user {request.user.username}: {str(e)}")
                messages.error(request, 'An error occurred while processing your deposit. Please try again.')
                if payment_debug_enabled():
                    logger.exception("[PAYMENT_DEBUG] deposit_exception", exc_info=True)
    else:
        form = DepositForm(user=request.user)
    
    return render(request, 'wallet/deposit.html', {'form': form, 'wallet': wallet})


@ratelimit(key=_get_rate_limit_key, rate='5/m', method='POST', block=True)
@login_required
@require_POST
@transaction.atomic
def withdraw_view(request):
    """
    Process withdrawal request
    Creates a Withdrawal record with PENDING status. Wallet balance is deducted
    immediately but can be restored if withdrawal fails.
    """
    try:
        wallet = request.user.wallet
    except Wallet.DoesNotExist:
        messages.error(request, 'Wallet not found')
        return redirect('wallet')
    
    if request.method == 'POST':
        form = WithdrawalForm(request.POST, user=request.user)
        if form.is_valid():
            try:
                amount = form.cleaned_data['amount']
                payment_method = form.cleaned_data['payment_method']
                
                if wallet.balance < amount:
                    messages.error(request, 'Insufficient balance for withdrawal')
                    return render(request, 'wallet/withdraw.html', {'form': form, 'wallet': wallet})
                
                # Create withdrawal record
                withdrawal = Withdrawal(
                    user=request.user,
                    amount=amount,
                    payment_method=payment_method,
                    status='PENDING',
                    wallet=wallet
                )
                
                # Deduct from wallet immediately
                wallet.balance -= amount
                wallet.save()
                
                withdrawal.save()
                
                # Create transaction record
                Transaction.objects.create(
                    wallet=wallet,
                    amount=-amount,
                    transaction_type='WITHDRAWAL',
                    description=f'Withdrawal request - {payment_method}',
                    reference_code=f'WD{withdrawal.id:06d}',
                    status='PENDING'
                )
                
                messages.success(request, f'Withdrawal request for ${amount} submitted successfully!')
                return redirect('wallet')
                
            except Exception as e:
                logger.error(f"Withdrawal error for user {request.user.username}: {str(e)}")
                messages.error(request, 'An error occurred while processing your withdrawal. Please try again.')
    else:
        form = WithdrawalForm(user=request.user)
    
    return render(request, 'wallet/withdraw.html', {'form': form, 'wallet': wallet})


@login_required
def transaction_history(request):
    """Display user's transaction history"""
    try:
        wallet = request.user.wallet
        transactions = wallet.transactions.all().order_by('-created_at')
    except Wallet.DoesNotExist:
        transactions = []
    
    return render(request, 'wallet/transactions.html', {
        'transactions': transactions
    })


@login_required
def payment_methods_list(request):
    """List user's saved payment methods"""
    payment_methods = SavedPaymentMethod.objects.filter(
        user=request.user,
        is_active=True
    ).order_by('-is_default', '-created_at')
    
    return render(request, 'wallet/payment_methods_list.html', {
        'payment_methods': payment_methods
    })


@ratelimit(key=_get_rate_limit_key, rate='10/h', method='POST', block=True)
@login_required
def payment_method_create(request):
    """Add a new payment method"""
    if request.method == 'POST':
        form = SavedPaymentMethodForm(request.POST, user=request.user)
        if form.is_valid():
            payment_method = form.save(commit=False)
            payment_method.user = request.user
            
            # If this is the first payment method of this type, make it default
            existing_count = SavedPaymentMethod.objects.filter(
                user=request.user,
                payment_method_type=payment_method.payment_method_type,
                is_active=True
            ).count()
            
            if existing_count == 0:
                payment_method.is_default = True
            
            payment_method.save()
            messages.success(request, 'Payment method added successfully!')
            return redirect('payment_methods_list')
    else:
        form = SavedPaymentMethodForm(user=request.user)
    
    return render(request, 'wallet/payment_method_form.html', {
        'form': form,
        'title': 'Add Payment Method'
    })


@ratelimit(key=_get_rate_limit_key, rate='10/h', method='POST', block=True)
@login_required
def payment_method_edit(request, payment_method_id):
    """Edit an existing payment method"""
    payment_method = get_object_or_404(
        SavedPaymentMethod,
        id=payment_method_id,
        user=request.user,
        is_active=True
    )
    
    if request.method == 'POST':
        form = SavedPaymentMethodForm(request.POST, instance=payment_method, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Payment method updated successfully!')
            return redirect('payment_methods_list')
    else:
        form = SavedPaymentMethodForm(instance=payment_method, user=request.user)
    
    return render(request, 'wallet/payment_method_form.html', {
        'form': form,
        'title': 'Edit Payment Method',
        'payment_method': payment_method
    })


@ratelimit(key=_get_rate_limit_key, rate='10/h', method='POST', block=True)
@login_required
def payment_method_delete(request, payment_method_id):
    """Delete a payment method"""
    payment_method = get_object_or_404(
        SavedPaymentMethod,
        id=payment_method_id,
        user=request.user,
        is_active=True
    )
    
    if request.method == 'POST':
        form = DeletePaymentMethodForm(request.POST)
        if form.is_valid() and form.cleaned_data['confirm']:
            # Soft delete by marking as inactive
            payment_method.is_active = False
            payment_method.save()
            
            # If this was a default payment method, set another as default
            if payment_method.is_default:
                remaining = SavedPaymentMethod.objects.filter(
                    user=request.user,
                    payment_method_type=payment_method.payment_method_type,
                    is_active=True
                ).first()
                
                if remaining:
                    remaining.is_default = True
                    remaining.save()
            
            messages.success(request, 'Payment method deleted successfully!')
            return redirect('payment_methods_list')
        else:
            messages.error(request, 'Please confirm deletion')
    
    return render(request, 'wallet/payment_method_delete.html', {
        'payment_method': payment_method
    })


@ratelimit(key=_get_rate_limit_key, rate='10/h', method='POST', block=True)
@login_required
def payment_method_set_default(request, payment_method_id):
    """Set a payment method as default"""
    payment_method = get_object_or_404(
        SavedPaymentMethod,
        id=payment_method_id,
        user=request.user,  # Security: Ensure user owns this payment method
        is_active=True
    )
    
    # Unset other defaults of same type
    SavedPaymentMethod.objects.filter(
        user=request.user,
        payment_method_type=payment_method.payment_method_type,
        is_default=True,
        is_active=True
    ).exclude(pk=payment_method.pk).update(is_default=False)
    
    # Set this as default
    payment_method.is_default = True
    payment_method.save()
    
    messages.success(request, f'"{payment_method.label}" set as default payment method.')
    return redirect('payment_methods_list')
