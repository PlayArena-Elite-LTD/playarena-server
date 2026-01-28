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
import logging

from .models import Wallet, Transaction, Deposit, Withdrawal, SavedPaymentMethod
from .forms import DepositForm, WithdrawalForm
from .payment_method_forms import SavedPaymentMethodForm, DeletePaymentMethodForm

logger = logging.getLogger(__name__)

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
                
                # Audit log: Deposit created
                from audit.utils import log_action
                log_action(
                    action='deposit_created',
                    user=request.user,
                    details={
                        'deposit_id': deposit.id,
                        'amount': str(deposit.amount),
                        'payment_method': deposit.payment_method,
                        'status': deposit.status,
                    },
                    request=request
                )
                
                # Initialize payment gateway transaction
                from wallet.payment_manager import get_payment_manager
                
                payment_manager = get_payment_manager()
                
                # Build callback URL for payment completion
                from django.urls import reverse
                callback_url = request.build_absolute_uri(reverse('wallet'))
                
                # Initialize payment
                payment_result = payment_manager.initialize_deposit(deposit, callback_url)
                
                if payment_result['success']:
                    # Update deposit with transaction reference
                    deposit.transaction_id = payment_result.get('payment_reference')
                    deposit.save()
                    
                    # If authorization URL is provided, redirect to payment gateway
                    if payment_result.get('authorization_url'):
                        # Store deposit ID in session for verification after redirect
                        request.session['pending_deposit_id'] = deposit.id
                        return redirect(payment_result['authorization_url'])
                    else:
                        # Bank transfer or other methods that don't require redirect
                        messages.success(
                            request,
                            f'Deposit request of ${amount:.2f} created successfully. '
                            f'Reference: {payment_result.get("payment_reference")}. '
                            f'Please complete the transfer and wait for verification.'
                        )
                        return redirect('wallet')
                else:
                    # Payment initialization failed
                    deposit.status = 'FAILED'
                    deposit.save()
                    
                    # Audit log: Deposit failed
                    from audit.utils import log_action
                    log_action(
                        action='deposit_failed',
                        user=request.user,
                        details={
                            'deposit_id': deposit.id,
                            'amount': str(deposit.amount),
                            'payment_method': deposit.payment_method,
                            'failure_reason': payment_result.get('failure_reason', 'Unknown error'),
                        },
                        request=request
                    )
                    
                    messages.error(
                        request,
                        f'Failed to initialize payment: {payment_result.get("failure_reason", "Unknown error")}'
                    )
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
    
    Security features:
    - IP address tracking
    - User agent tracking
    - Fraud detection
    - Comprehensive logging
    
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
                
                # Security: Capture IP address and user agent
                from wallet.error_handlers import _get_client_ip
                ip_address = _get_client_ip(request)
                user_agent = request.META.get('HTTP_USER_AGENT', '')[:500]  # Limit length
                
                # Security: Detect suspicious withdrawal activity
                from wallet.error_handlers import detect_suspicious_withdrawal_activity, log_security_event
                suspicious, reasons = detect_suspicious_withdrawal_activity(request, amount, payment_method)
                
                if suspicious:
                    # Log suspicious activity but don't block (flag for review)
                    log_security_event(
                        'suspicious_withdrawal_activity',
                        {
                            'reasons': reasons,
                            'amount': float(amount),
                            'payment_method': payment_method,
                            'user_id': request.user.id,
                            'username': request.user.username,
                        },
                        request=request,
                        severity='WARNING'
                    )
                    logger.warning(
                        f"Suspicious withdrawal activity detected for user {request.user.username}: {reasons}"
                    )
                
                # Create Withdrawal instance (validation happens in clean())
                withdrawal = Withdrawal(
                    user=request.user,
                    amount=amount,
                    payment_method=payment_method,
                    account_details=account_details,
                    status='PENDING',  # Start as PENDING
                    wallet=wallet,
                    ip_address=ip_address,  # Security: Track IP address
                    user_agent=user_agent  # Security: Track user agent
                )
                
                # Run validation (checks amount limits, balance, etc.)
                withdrawal.full_clean()
                withdrawal.save()
                    
                # Send notification for withdrawal creation
                from wallet.notifications import notify_withdrawal_created
                notify_withdrawal_created(withdrawal)
                
                logger.info(
                    f"Withdrawal {withdrawal.id} created - "
                    f"User: {request.user.username}, Amount: ${amount}, "
                    f"IP: {ip_address}, Suspicious: {suspicious}"
                )
                
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


@login_required
def payment_method_create(request):
    """Create a new saved payment method"""
    if request.method == 'POST':
        form = SavedPaymentMethodForm(request.POST, user=request.user)
        if form.is_valid():
            payment_method = form.save(commit=False)
            payment_method.user = request.user
            payment_method.save()
            messages.success(request, f'Payment method "{payment_method.label}" saved successfully.')
            return redirect('payment_methods_list')
    else:
        form = SavedPaymentMethodForm(user=request.user)
    
    return render(request, 'wallet/payment_method_form.html', {
        'form': form,
        'title': 'Add Payment Method'
    })


@login_required
def payment_method_edit(request, payment_method_id):
    """Edit an existing saved payment method"""
    payment_method = get_object_or_404(
        SavedPaymentMethod,
        id=payment_method_id,
        user=request.user  # Security: Ensure user owns this payment method
    )
    
    if request.method == 'POST':
        form = SavedPaymentMethodForm(request.POST, instance=payment_method, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, f'Payment method "{payment_method.label}" updated successfully.')
            return redirect('payment_methods_list')
    else:
        form = SavedPaymentMethodForm(instance=payment_method, user=request.user)
    
    return render(request, 'wallet/payment_method_form.html', {
        'form': form,
        'payment_method': payment_method,
        'title': 'Edit Payment Method'
    })


@login_required
@require_POST
def payment_method_delete(request, payment_method_id):
    """Delete a saved payment method"""
    payment_method = get_object_or_404(
        SavedPaymentMethod,
        id=payment_method_id,
        user=request.user  # Security: Ensure user owns this payment method
    )
    
    form = DeletePaymentMethodForm(request.POST)
    if form.is_valid() and form.cleaned_data['confirm']:
        label = payment_method.label
        payment_method.delete()
        messages.success(request, f'Payment method "{label}" deleted successfully.')
    else:
        messages.error(request, 'Please confirm deletion.')
    
    return redirect('payment_methods_list')


@login_required
@require_POST
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
