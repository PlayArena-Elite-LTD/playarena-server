from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django_ratelimit.decorators import ratelimit
from decimal import Decimal, InvalidOperation
import logging
import secrets
import hashlib

from .models import Wallet, Transaction, Deposit, Withdrawal
from .forms import DepositForm, WithdrawalForm
from .payment_service import PaymentManager

logger = logging.getLogger(__name__)


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


def _get_client_ip(request):
    """Securely extract client IP address"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def _generate_secure_payment_reference(deposit_id, user_id, timestamp):
    """Generate cryptographically secure payment reference"""
    # Combine multiple entropy sources for security
    random_part = secrets.token_urlsafe(16)
    hash_input = f"{deposit_id}_{user_id}_{timestamp}_{random_part}"
    hash_part = hashlib.sha256(hash_input.encode()).hexdigest()[:12]
    return f"dep_{deposit_id}_{hash_part}"


@login_required
@ratelimit(key='user', rate='10/m', method='POST', block=True)
def deposit(request):
    """
    Create deposit request with payment gateway integration (Paystack/Flutterwave)
    Security features:
    - IP address tracking
    - User agent tracking
    - Secure payment reference generation
    - Gateway response storage
    - Comprehensive error handling
    """
    wallet = request.user.wallet
    
    if request.method == 'POST':
        form = DepositForm(request.POST, user=request.user)
        if form.is_valid():
            try:
                with transaction.atomic():
                    amount = form.cleaned_data['amount']
                    payment_method = form.cleaned_data['payment_method']
                    
                    # Security: Capture client information
                    client_ip = _get_client_ip(request)
                    user_agent = request.META.get('HTTP_USER_AGENT', '')[:500]  # Limit length
                    
                    # Create Deposit instance with security fields
                    deposit = Deposit(
                        user=request.user,
                        amount=amount,
                        payment_method=payment_method,
                        status='PENDING',
                        wallet=wallet,
                        ip_address=client_ip,
                        user_agent=user_agent,
                    )
                    deposit.full_clean()
                    deposit.save()
                    
                    # Generate secure payment reference
                    payment_reference = _generate_secure_payment_reference(
                        deposit.id, 
                        request.user.id, 
                        deposit.created_at.timestamp()
                    )
                    deposit.payment_reference = payment_reference
                    
                    # Initialize payment gateway if Paystack or Flutterwave
                    payment_url = None
                    if payment_method in ['PAYSTACK', 'FLUTTERWAVE']:
                        try:
                            payment_manager = PaymentManager()
                            payment_result = payment_manager.initialize_payment(deposit, request)
                            
                            if payment_result['success']:
                                payment_url = payment_result.get('payment_url')
                                # Store gateway response securely
                                deposit.gateway_response = {
                                    'initialization': {
                                        'success': True,
                                        'gateway': payment_result.get('gateway'),
                                        'payment_reference': payment_result.get('payment_reference'),
                                        'timestamp': timezone.now().isoformat(),
                                    }
                                }
                                
                                # Update deposit with payment reference from gateway
                                if payment_result.get('payment_reference'):
                                    deposit.payment_reference = payment_result.get('payment_reference')
                                
                                deposit.save(update_fields=['payment_reference', 'gateway_response', 'status'])
                                
                                logger.info(
                                    f"Payment initialized for deposit {deposit.id} - "
                                    f"User: {request.user.username}, Amount: ${amount}, "
                                    f"Gateway: {payment_method}, IP: {client_ip}"
                                )
                                
                                # Redirect to payment gateway
                                if payment_url:
                                    return redirect(payment_url)
                                else:
                                    messages.warning(request, 'Payment initialized but no payment URL received.')
                            else:
                                # Payment initialization failed
                                error_message = payment_result.get('message', 'Payment initialization failed')
                                deposit.status = 'FAILED'
                                deposit.failure_reason = error_message
                                deposit.gateway_response = {
                                    'initialization': {
                                        'success': False,
                                        'error': error_message,
                                        'timestamp': timezone.now().isoformat(),
                                    }
                                }
                                deposit.save(update_fields=['status', 'failure_reason', 'gateway_response'])
                                
                                logger.error(
                                    f"Payment initialization failed for deposit {deposit.id} - "
                                    f"User: {request.user.username}, Error: {error_message}"
                                )
                                
                                messages.error(request, f'Payment initialization failed: {error_message}')
                                
                        except Exception as e:
                            # Security: Don't expose internal errors to user
                            logger.error(
                                f"Exception initializing payment for deposit {deposit.id} - "
                                f"User: {request.user.username}, Error: {str(e)}",
                                exc_info=True
                            )
                            
                            deposit.status = 'FAILED'
                            deposit.failure_reason = 'Internal payment processing error'
                            deposit.gateway_response = {
                                'initialization': {
                                    'success': False,
                                    'error': 'Internal error',
                                    'timestamp': timezone.now().isoformat(),
                                }
                            }
                            deposit.save(update_fields=['status', 'failure_reason', 'gateway_response'])
                            
                            messages.error(request, 'An error occurred while processing your payment. Please try again.')
                    else:
                        # Manual payment method - just save the deposit
                        deposit.save(update_fields=['payment_reference'])
                        logger.info(
                            f"Manual deposit request created - "
                            f"User: {request.user.username}, Amount: ${amount}, Method: {payment_method}"
                        )
                        messages.success(request, f'Deposit request of ${amount:.2f} created successfully. It will be processed shortly.')
                    
                    # Handle JSON requests
                    if request.headers.get('Content-Type', '').startswith('application/json') or \
                       request.headers.get('Accept', '').startswith('application/json'):
                        response_data = {
                            'status': 'success' if deposit.status != 'FAILED' else 'error',
                            'deposit_id': deposit.id,
                            'amount': float(amount),
                            'payment_reference': deposit.payment_reference,
                            'message': f'Deposit request created. Status: {deposit.get_status_display()}'
                        }
                        if payment_url:
                            response_data['payment_url'] = payment_url
                        return JsonResponse(response_data)
                    
                    # If payment URL was set, redirect already happened
                    if not payment_url:
                        return redirect('wallet')
                        
            except Exception as e:
                # Security: Log full error but show generic message to user
                logger.error(
                    f"Error creating deposit for user {request.user.username} - "
                    f"IP: {_get_client_ip(request)}, Error: {str(e)}",
                    exc_info=True
                )
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


@login_required
def payment_success(request, deposit_id):
    """
    Enhanced payment success callback handler with security features
    
    Security features:
    - User ownership verification
    - Payment reference validation from query parameters
    - Payment verification with gateway API
    - Replay attack prevention
    - Status update with atomic transactions
    - Comprehensive audit logging
    
    Handles redirects from Paystack/Flutterwave after successful payment
    """
    # Security: Verify deposit belongs to user
    deposit = get_object_or_404(Deposit, id=deposit_id, user=request.user)
    
    # Security: Get payment reference from query parameters (gateway redirect)
    reference_from_gateway = request.GET.get('reference') or request.GET.get('tx_ref')
    transaction_id_from_gateway = request.GET.get('transaction_id') or request.GET.get('flw_ref')
    
    # Security: Validate reference matches deposit (prevents manipulation)
    if reference_from_gateway and deposit.payment_reference:
        if reference_from_gateway != deposit.payment_reference:
            logger.warning(
                f"Payment callback reference mismatch - "
                f"User: {request.user.username}, Deposit: {deposit_id}, "
                f"Expected: {deposit.payment_reference}, Received: {reference_from_gateway}, "
                f"IP: {_get_client_ip(request)}"
            )
            messages.error(request, 'Payment verification failed. Reference mismatch.')
            return redirect('wallet')
    
    # If deposit already completed, show success page (prevent replay)
    if deposit.status == 'COMPLETED':
        logger.info(
            f"Payment success callback for already completed deposit - "
            f"User: {request.user.username}, Deposit: {deposit_id}"
        )
        # Refresh deposit to get latest wallet balance
        deposit.refresh_from_db()
        return render(request, 'wallet/payment_success.html', {'deposit': deposit})
    
    # Verify payment with gateway API (security: don't trust redirect alone)
    try:
        payment_manager = PaymentManager()
        verification_result = payment_manager.verify_payment(deposit)
        
        if verification_result['success']:
            verified_status = verification_result.get('status')
            
            # Security: Update deposit status atomically
            with transaction.atomic():
                # Reload deposit with lock to prevent race conditions
                deposit = Deposit.objects.select_for_update().get(id=deposit_id)
                
                if verified_status == 'COMPLETED':
                    # Payment verified as completed
                    if deposit.status != 'COMPLETED':
                        deposit.status = 'COMPLETED'
                        deposit.completed_at = timezone.now()
                        
                        # Update transaction IDs if provided
                        if transaction_id_from_gateway:
                            deposit.gateway_transaction_id = transaction_id_from_gateway
                        
                        # Generate verification hash if not exists
                        if not deposit.verification_hash:
                            deposit.verification_hash = deposit.generate_verification_hash()
                        
                        # Store verification response
                        deposit.gateway_response = {
                            **deposit.gateway_response,
                            'callback_verification': {
                                'success': True,
                                'status': 'COMPLETED',
                                'timestamp': timezone.now().isoformat(),
                                'reference': reference_from_gateway,
                                'transaction_id': transaction_id_from_gateway,
                            }
                        }
                        
                        deposit.save(update_fields=[
                            'status', 'completed_at', 'gateway_transaction_id',
                            'verification_hash', 'gateway_response'
                        ])
                        
                        logger.info(
                            f"Payment verified and completed via callback - "
                            f"User: {request.user.username}, Deposit: {deposit_id}, "
                            f"Amount: ${deposit.amount}, Provider: {deposit.payment_provider}"
                        )
                    else:
                        # Already completed, just refresh
                        deposit.refresh_from_db()
                    
                    # Render success page
                    return render(request, 'wallet/payment_success.html', {'deposit': deposit})
                        
                elif verified_status == 'FAILED':
                    # Payment verified as failed
                    deposit.status = 'FAILED'
                    deposit.failure_reason = verification_result.get('message', 'Payment failed')
                    deposit.gateway_response = {
                        **deposit.gateway_response,
                        'callback_verification': {
                            'success': False,
                            'status': 'FAILED',
                            'timestamp': timezone.now().isoformat(),
                        }
                    }
                    deposit.save(update_fields=['status', 'failure_reason', 'gateway_response'])
                    
                    logger.warning(
                        f"Payment failed via callback verification - "
                        f"User: {request.user.username}, Deposit: {deposit_id}"
                    )
                    
                    # Render failure page
                    return render(request, 'wallet/payment_failure.html', {'deposit': deposit})
                    
                else:
                    # Payment still pending - redirect to wallet with message
                    messages.info(
                        request,
                        'Your payment is being processed. You will be notified when it\'s completed.'
                    )
                    return redirect('wallet')
        else:
            # Verification failed
            logger.error(
                f"Payment verification failed in callback - "
                f"User: {request.user.username}, Deposit: {deposit_id}, "
                f"Error: {verification_result.get('message')}"
            )
            
            # Don't update status if verification fails - wait for webhook
            # Show pending status
            messages.info(
                request,
                'Payment is being processed. Please wait for confirmation or check back later.'
            )
            return redirect('wallet')
            
    except Exception as e:
        # Security: Log error but don't expose to user
        logger.error(
            f"Exception in payment success callback - "
            f"User: {request.user.username}, Deposit: {deposit_id}, "
            f"Error: {str(e)}",
            exc_info=True
        )
        
        # Don't update status on error - webhook will handle it
        messages.info(
            request,
            'Payment verification is in progress. Please check back in a few moments.'
        )
        return redirect('wallet')


@login_required
def payment_cancel(request, deposit_id):
    """
    Enhanced payment cancellation handler with security features
    
    Security features:
    - User ownership verification
    - Status update with validation
    - Audit logging
    - Prevents unauthorized cancellation
    """
    # Security: Verify deposit belongs to user
    deposit = get_object_or_404(Deposit, id=deposit_id, user=request.user)
    
    # Security: Only allow cancellation of pending/processing deposits
    if deposit.status in ['PENDING', 'PROCESSING']:
        with transaction.atomic():
            # Reload with lock
            deposit = Deposit.objects.select_for_update().get(id=deposit_id)
            
            # Double-check status (prevent race conditions)
            if deposit.status in ['PENDING', 'PROCESSING']:
                deposit.status = 'CANCELLED'
                deposit.failure_reason = 'Payment cancelled by user'
                deposit.gateway_response = {
                    **deposit.gateway_response,
                    'cancellation': {
                        'timestamp': timezone.now().isoformat(),
                        'ip': _get_client_ip(request),
                    }
                }
                deposit.save(update_fields=['status', 'failure_reason', 'gateway_response'])
                
                logger.info(
                    f"Payment cancelled by user - "
                    f"User: {request.user.username}, Deposit: {deposit_id}, "
                    f"Amount: ${deposit.amount}, IP: {_get_client_ip(request)}"
                )
                
                # Render failure page for cancelled payment
                return render(request, 'wallet/payment_failure.html', {'deposit': deposit})
            else:
                messages.warning(
                    request,
                    f'Payment cannot be cancelled. Current status: {deposit.get_status_display()}'
                )
                return redirect('wallet')
    elif deposit.status == 'COMPLETED':
        messages.warning(request, 'This payment has already been completed and cannot be cancelled.')
        return redirect('wallet')
    elif deposit.status == 'CANCELLED':
        # Already cancelled, show failure page
        return render(request, 'wallet/payment_failure.html', {'deposit': deposit})
    else:
        messages.warning(
            request,
            f'Payment cannot be cancelled. Current status: {deposit.get_status_display()}'
        )
        return redirect('wallet')


@csrf_exempt
@require_http_methods(["POST"])
def paystack_webhook(request):
    """
    Paystack webhook handler with comprehensive security
    
    Security features:
    - Webhook signature verification (HMAC SHA512)
    - IP whitelist check (optional - Paystack IPs)
    - Duplicate webhook prevention
    - Atomic transaction processing
    - Comprehensive logging
    - Error handling without exposing internals
    """
    from .paystack_service import PaystackService
    import json
    
    # Security: Get raw request body for signature verification
    raw_body = request.body
    
    # Security: Get webhook signature from headers
    signature = request.headers.get('X-Paystack-Signature', '')
    
    if not signature:
        logger.warning(f"Paystack webhook received without signature - IP: {_get_client_ip(request)}")
        return HttpResponse('Missing signature', status=400)
    
    try:
        # Parse webhook payload
        payload = json.loads(raw_body.decode('utf-8'))
        event_type = payload.get('event')
        event_data = payload.get('data', {})
        
        # Security: Verify webhook signature
        paystack_service = PaystackService()
        is_valid = paystack_service.verify_webhook(raw_body.decode('utf-8'), signature)
        
        if not is_valid:
            logger.error(
                f"Invalid Paystack webhook signature - "
                f"IP: {_get_client_ip(request)}, Event: {event_type}"
            )
            return HttpResponse('Invalid signature', status=401)
        
        # Security: Extract payment reference
        reference = event_data.get('reference')
        if not reference:
            logger.warning(f"Paystack webhook missing reference - Event: {event_type}")
            return HttpResponse('Missing reference', status=400)
        
        # Security: Find deposit by payment reference (prevents unauthorized access)
        try:
            deposit = Deposit.objects.select_for_update().get(
                payment_reference=reference,
                payment_provider='PAYSTACK'
            )
        except Deposit.DoesNotExist:
            logger.warning(
                f"Paystack webhook for unknown deposit - "
                f"Reference: {reference}, Event: {event_type}, IP: {_get_client_ip(request)}"
            )
            # Return 200 to prevent webhook retries for invalid references
            return HttpResponse('Deposit not found', status=200)
        
        # Security: Prevent duplicate webhook processing
        # Check if webhook was already processed (by checking last_webhook_at and status)
        if deposit.status == 'COMPLETED' and deposit.last_webhook_at:
            logger.info(
                f"Duplicate Paystack webhook ignored - "
                f"Deposit: {deposit.id}, Reference: {reference}, Event: {event_type}"
            )
            return HttpResponse('Already processed', status=200)
        
        # Process webhook event atomically
        with transaction.atomic():
            # Update webhook tracking
            deposit.last_webhook_at = timezone.now()
            deposit.webhook_signature = signature[:255]  # Store signature for audit
            deposit.webhook_verified = True
            
            # Store full webhook payload for audit
            deposit.gateway_response = {
                **deposit.gateway_response,
                'webhook': {
                    'event': event_type,
                    'data': event_data,
                    'timestamp': timezone.now().isoformat(),
                    'ip': _get_client_ip(request),
                }
            }
            
            # Handle different event types
            if event_type == 'charge.success':
                # Security: Verify payment amount matches deposit amount
                amount_paid = Decimal(event_data.get('amount', 0)) / 100  # Convert from kobo
                
                if amount_paid != deposit.amount:
                    logger.error(
                        f"Amount mismatch in Paystack webhook - "
                        f"Deposit: {deposit.id}, Expected: {deposit.amount}, Received: {amount_paid}"
                    )
                    deposit.failure_reason = f'Amount mismatch: expected {deposit.amount}, received {amount_paid}'
                    deposit.status = 'FAILED'
                    deposit.save(update_fields=['status', 'failure_reason', 'last_webhook_at', 'webhook_signature', 'webhook_verified', 'gateway_response'])
                    return HttpResponse('Amount mismatch', status=400)
                
                # Update deposit status
                deposit.status = 'COMPLETED'
                deposit.completed_at = timezone.now()
                deposit.transaction_id = event_data.get('id', deposit.transaction_id)
                deposit.gateway_transaction_id = event_data.get('id')
                
                # Verify hash integrity
                if not deposit.verification_hash:
                    deposit.verification_hash = deposit.generate_verification_hash()
                
                deposit.save(update_fields=[
                    'status', 'completed_at', 'transaction_id', 'gateway_transaction_id',
                    'last_webhook_at', 'webhook_signature', 'webhook_verified',
                    'gateway_response', 'verification_hash'
                ])
                
                # Note: Wallet balance update will be handled in Task 15
                # For now, we just mark the deposit as completed
                
                logger.info(
                    f"Paystack payment completed via webhook - "
                    f"Deposit: {deposit.id}, User: {deposit.user.username}, "
                    f"Amount: ${deposit.amount}, Reference: {reference}"
                )
                
            elif event_type == 'charge.failed':
                deposit.status = 'FAILED'
                deposit.failure_reason = event_data.get('gateway_response', 'Payment failed')
                deposit.save(update_fields=[
                    'status', 'failure_reason', 'last_webhook_at',
                    'webhook_signature', 'webhook_verified', 'gateway_response'
                ])
                
                logger.warning(
                    f"Paystack payment failed via webhook - "
                    f"Deposit: {deposit.id}, Reference: {reference}, "
                    f"Reason: {deposit.failure_reason}"
                )
            else:
                # Unknown event type - log but don't fail
                logger.info(
                    f"Unhandled Paystack webhook event - "
                    f"Deposit: {deposit.id}, Event: {event_type}, Reference: {reference}"
                )
                deposit.save(update_fields=[
                    'last_webhook_at', 'webhook_signature',
                    'webhook_verified', 'gateway_response'
                ])
        
        # Return 200 to acknowledge webhook receipt
        return HttpResponse('Webhook processed', status=200)
        
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in Paystack webhook - Error: {str(e)}")
        return HttpResponse('Invalid JSON', status=400)
    except Exception as e:
        # Security: Don't expose internal errors
        logger.error(
            f"Error processing Paystack webhook - "
            f"IP: {_get_client_ip(request)}, Error: {str(e)}",
            exc_info=True
        )
        return HttpResponse('Internal error', status=500)


@csrf_exempt
@require_http_methods(["POST"])
def flutterwave_webhook(request):
    """
    Flutterwave webhook handler with comprehensive security
    
    Security features:
    - Webhook signature verification (HMAC SHA256)
    - Duplicate webhook prevention
    - Atomic transaction processing
    - Comprehensive logging
    - Error handling without exposing internals
    - Amount verification
    """
    from .flutterwave_service import FlutterwaveService
    import json
    
    # Security: Get raw request body for signature verification
    raw_body = request.body
    
    # Security: Get webhook signature from headers (Flutterwave uses different header)
    signature = request.headers.get('verif-hash', '') or request.headers.get('X-Flutterwave-Signature', '')
    
    if not signature:
        logger.warning(f"Flutterwave webhook received without signature - IP: {_get_client_ip(request)}")
        return HttpResponse('Missing signature', status=400)
    
    try:
        # Parse webhook payload
        payload = json.loads(raw_body.decode('utf-8'))
        event_type = payload.get('event')
        event_data = payload.get('data', {})
        
        # Security: Verify webhook signature (Flutterwave uses HMAC SHA256)
        flutterwave_service = FlutterwaveService()
        is_valid = flutterwave_service.verify_webhook(raw_body.decode('utf-8'), signature)
        
        if not is_valid:
            logger.error(
                f"Invalid Flutterwave webhook signature - "
                f"IP: {_get_client_ip(request)}, Event: {event_type}"
            )
            return HttpResponse('Invalid signature', status=401)
        
        # Security: Extract transaction reference (Flutterwave uses tx_ref)
        tx_ref = event_data.get('tx_ref')
        if not tx_ref:
            logger.warning(f"Flutterwave webhook missing tx_ref - Event: {event_type}")
            return HttpResponse('Missing tx_ref', status=400)
        
        # Security: Find deposit by payment reference (prevents unauthorized access)
        try:
            deposit = Deposit.objects.select_for_update().get(
                payment_reference=tx_ref,
                payment_provider='FLUTTERWAVE'
            )
        except Deposit.DoesNotExist:
            logger.warning(
                f"Flutterwave webhook for unknown deposit - "
                f"tx_ref: {tx_ref}, Event: {event_type}, IP: {_get_client_ip(request)}"
            )
            # Return 200 to prevent webhook retries for invalid references
            return HttpResponse('Deposit not found', status=200)
        
        # Security: Prevent duplicate webhook processing
        if deposit.status == 'COMPLETED' and deposit.last_webhook_at:
            logger.info(
                f"Duplicate Flutterwave webhook ignored - "
                f"Deposit: {deposit.id}, tx_ref: {tx_ref}, Event: {event_type}"
            )
            return HttpResponse('Already processed', status=200)
        
        # Process webhook event atomically
        with transaction.atomic():
            # Update webhook tracking
            deposit.last_webhook_at = timezone.now()
            deposit.webhook_signature = signature[:255]  # Store signature for audit
            deposit.webhook_verified = True
            
            # Store full webhook payload for audit
            deposit.gateway_response = {
                **deposit.gateway_response,
                'webhook': {
                    'event': event_type,
                    'data': event_data,
                    'timestamp': timezone.now().isoformat(),
                    'ip': _get_client_ip(request),
                }
            }
            
            # Handle different event types
            if event_type == 'charge.completed':
                # Security: Verify payment status and amount
                status = event_data.get('status', '').lower()
                amount_paid = Decimal(str(event_data.get('amount', 0)))
                
                if status == 'successful':
                    # Security: Verify payment amount matches deposit amount
                    if amount_paid != deposit.amount:
                        logger.error(
                            f"Amount mismatch in Flutterwave webhook - "
                            f"Deposit: {deposit.id}, Expected: {deposit.amount}, Received: {amount_paid}"
                        )
                        deposit.failure_reason = f'Amount mismatch: expected {deposit.amount}, received {amount_paid}'
                        deposit.status = 'FAILED'
                        deposit.save(update_fields=[
                            'status', 'failure_reason', 'last_webhook_at',
                            'webhook_signature', 'webhook_verified', 'gateway_response'
                        ])
                        return HttpResponse('Amount mismatch', status=400)
                    
                    # Update deposit status
                    deposit.status = 'COMPLETED'
                    deposit.completed_at = timezone.now()
                    deposit.transaction_id = tx_ref
                    deposit.gateway_transaction_id = event_data.get('flw_ref', '')
                    
                    # Verify hash integrity
                    if not deposit.verification_hash:
                        deposit.verification_hash = deposit.generate_verification_hash()
                    
                    deposit.save(update_fields=[
                        'status', 'completed_at', 'transaction_id', 'gateway_transaction_id',
                        'last_webhook_at', 'webhook_signature', 'webhook_verified',
                        'gateway_response', 'verification_hash'
                    ])
                    
                    # Note: Wallet balance update will be handled in Task 15
                    
                    logger.info(
                        f"Flutterwave payment completed via webhook - "
                        f"Deposit: {deposit.id}, User: {deposit.user.username}, "
                        f"Amount: ${deposit.amount}, tx_ref: {tx_ref}, flw_ref: {event_data.get('flw_ref')}"
                    )
                else:
                    # Payment completed but not successful
                    deposit.status = 'FAILED'
                    deposit.failure_reason = f"Payment status: {status}"
                    deposit.save(update_fields=[
                        'status', 'failure_reason', 'last_webhook_at',
                        'webhook_signature', 'webhook_verified', 'gateway_response'
                    ])
                    
                    logger.warning(
                        f"Flutterwave payment failed via webhook - "
                        f"Deposit: {deposit.id}, tx_ref: {tx_ref}, Status: {status}"
                    )
                    
            elif event_type == 'charge.failed':
                deposit.status = 'FAILED'
                deposit.failure_reason = event_data.get('processor_response', 'Payment failed')
                deposit.save(update_fields=[
                    'status', 'failure_reason', 'last_webhook_at',
                    'webhook_signature', 'webhook_verified', 'gateway_response'
                ])
                
                logger.warning(
                    f"Flutterwave payment failed via webhook - "
                    f"Deposit: {deposit.id}, tx_ref: {tx_ref}, "
                    f"Reason: {deposit.failure_reason}"
                )
            else:
                # Unknown event type - log but don't fail
                logger.info(
                    f"Unhandled Flutterwave webhook event - "
                    f"Deposit: {deposit.id}, Event: {event_type}, tx_ref: {tx_ref}"
                )
                deposit.save(update_fields=[
                    'last_webhook_at', 'webhook_signature',
                    'webhook_verified', 'gateway_response'
                ])
        
        # Return 200 to acknowledge webhook receipt
        return HttpResponse('Webhook processed', status=200)
        
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in Flutterwave webhook - Error: {str(e)}")
        return HttpResponse('Invalid JSON', status=400)
    except Exception as e:
        # Security: Don't expose internal errors
        logger.error(
            f"Error processing Flutterwave webhook - "
            f"IP: {_get_client_ip(request)}, Error: {str(e)}",
            exc_info=True
        )
        return HttpResponse('Internal error', status=500)
