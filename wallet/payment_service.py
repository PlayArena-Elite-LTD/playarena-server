"""
Payment Manager - Unified Interface for Payment Gateways

This module provides a unified interface for processing payments through
Flutterwave and Paystack payment gateways using the separate service classes.
"""

import logging
from decimal import Decimal
from django.conf import settings
from django.urls import reverse

from .paystack_service import PaystackService
from .flutterwave_service import FlutterwaveService

logger = logging.getLogger(__name__)


class PaymentManager:
    """Unified payment manager that delegates to specific gateway services"""
    
    def __init__(self):
        """Initialize payment manager with gateway services"""
        self.paystack_service = PaystackService()
        self.flutterwave_service = FlutterwaveService()
    
    def get_service(self, provider_name):
        """
        Get the appropriate payment service based on provider name
        
        Args:
            provider_name: 'PAYSTACK' or 'FLUTTERWAVE'
        
        Returns:
            PaystackService or FlutterwaveService instance
        """
        if provider_name == 'PAYSTACK':
            return self.paystack_service
        elif provider_name == 'FLUTTERWAVE':
            return self.flutterwave_service
        else:
            raise ValueError(f"Unknown payment provider: {provider_name}")
    
    def initialize_payment(self, deposit, request):
        """
        Initialize payment based on payment method
        
        Args:
            deposit: Deposit model instance
            request: Django request object (for building callback URLs)
        
        Returns:
            dict: {
                'success': bool,
                'payment_url': str (for redirect),
                'payment_reference': str,
                'message': str,
                'gateway': str
            }
        """
        payment_method = deposit.payment_method
        amount = deposit.amount
        user = deposit.user
        
        try:
            if payment_method == 'FLUTTERWAVE':
                return self._initialize_flutterwave_payment(deposit, request, amount, user)
            elif payment_method == 'PAYSTACK':
                return self._initialize_paystack_payment(deposit, request, amount, user)
            else:
                # For other payment methods, return manual processing
                return {
                    'success': True,
                    'payment_url': None,
                    'payment_reference': None,
                    'message': 'Payment will be processed manually',
                    'gateway': payment_method
                }
        except Exception as e:
            logger.error(f"Error initializing payment for deposit {deposit.id}: {str(e)}")
            return {
                'success': False,
                'payment_url': None,
                'payment_reference': None,
                'message': f'Payment initialization failed: {str(e)}',
                'gateway': payment_method
            }
    
    def _initialize_flutterwave_payment(self, deposit, request, amount, user):
        """Initialize Flutterwave payment using FlutterwaveService"""
        try:
            # Build callback URL
            callback_url = request.build_absolute_uri(
                reverse('payment_success', kwargs={'deposit_id': deposit.id})
            )
            
            # Create transaction reference
            tx_ref = f"deposit_{deposit.id}_{deposit.created_at.timestamp()}"
            
            # Initialize payment using FlutterwaveService
            result = self.flutterwave_service.initialize_payment(
                amount=amount,
                email=user.email,
                tx_ref=tx_ref,
                redirect_url=callback_url,
                customer_name=user.get_full_name() or user.username,
                currency=getattr(settings, 'DEFAULT_PAYMENT_CURRENCY', 'NGN'),
                metadata={
                    'deposit_id': deposit.id,
                    'user_id': user.id,
                }
            )
            
            if result['success']:
                # Update deposit with transaction reference
                deposit.transaction_id = result.get('tx_ref') or tx_ref
                deposit.status = 'PROCESSING'
                deposit.save(update_fields=['transaction_id', 'status'])
                
                logger.info(f"Flutterwave payment initialized for deposit {deposit.id}: {result.get('tx_ref')}")
                
                return {
                    'success': True,
                    'payment_url': result.get('payment_link'),
                    'payment_reference': result.get('tx_ref'),
                    'message': 'Payment initialized successfully',
                    'gateway': 'FLUTTERWAVE'
                }
            else:
                return {
                    'success': False,
                    'payment_url': None,
                    'payment_reference': None,
                    'message': result.get('message', 'Flutterwave payment initialization failed'),
                    'gateway': 'FLUTTERWAVE'
                }
        except Exception as e:
            logger.error(f"Exception initializing Flutterwave payment: {str(e)}")
            return {
                'success': False,
                'payment_url': None,
                'payment_reference': None,
                'message': f'Error: {str(e)}',
                'gateway': 'FLUTTERWAVE'
            }
    
    def _initialize_paystack_payment(self, deposit, request, amount, user):
        """Initialize Paystack payment using PaystackService"""
        try:
            # Build callback URL
            callback_url = request.build_absolute_uri(
                reverse('payment_success', kwargs={'deposit_id': deposit.id})
            )
            
            # Create payment reference
            payment_reference = f"deposit_{deposit.id}_{deposit.created_at.timestamp()}"
            
            # Initialize payment using PaystackService
            result = self.paystack_service.initialize_payment(
                amount=amount,
                email=user.email,
                reference=payment_reference,
                callback_url=callback_url,
                metadata={
                    'deposit_id': deposit.id,
                    'user_id': user.id,
                }
            )
            
            if result['success']:
                # Update deposit with transaction reference
                deposit.transaction_id = result.get('reference') or payment_reference
                deposit.status = 'PROCESSING'
                deposit.save(update_fields=['transaction_id', 'status'])
                
                logger.info(f"Paystack payment initialized for deposit {deposit.id}: {result.get('reference')}")
                
                return {
                    'success': True,
                    'payment_url': result.get('authorization_url'),
                    'payment_reference': result.get('reference'),
                    'message': 'Payment initialized successfully',
                    'gateway': 'PAYSTACK'
                }
            else:
                return {
                    'success': False,
                    'payment_url': None,
                    'payment_reference': None,
                    'message': result.get('message', 'Paystack payment initialization failed'),
                    'gateway': 'PAYSTACK'
                }
        except Exception as e:
            logger.error(f"Exception initializing Paystack payment: {str(e)}")
            return {
                'success': False,
                'payment_url': None,
                'payment_reference': None,
                'message': f'Error: {str(e)}',
                'gateway': 'PAYSTACK'
            }
    
    def verify_payment(self, deposit):
        """
        Verify payment status with payment gateway
        
        Args:
            deposit: Deposit model instance
        
        Returns:
            dict: {
                'success': bool,
                'status': str (COMPLETED, FAILED, PENDING),
                'message': str
            }
        """
        if not deposit.transaction_id:
            return {
                'success': False,
                'status': 'PENDING',
                'message': 'No transaction reference found'
            }
        
        payment_method = deposit.payment_method
        
        try:
            if payment_method == 'FLUTTERWAVE':
                return self._verify_flutterwave_payment(deposit)
            elif payment_method == 'PAYSTACK':
                return self._verify_paystack_payment(deposit)
            else:
                return {
                    'success': True,
                    'status': 'PENDING',
                    'message': 'Manual verification required'
                }
        except Exception as e:
            logger.error(f"Error verifying payment for deposit {deposit.id}: {str(e)}")
            return {
                'success': False,
                'status': 'PENDING',
                'message': f'Verification error: {str(e)}'
            }
    
    def _verify_flutterwave_payment(self, deposit):
        """Verify Flutterwave payment status using FlutterwaveService"""
        try:
            result = self.flutterwave_service.verify_payment(deposit.transaction_id)
            
            if result['success']:
                status = result.get('status', '').lower()
                if status == 'successful':
                    return {
                        'success': True,
                        'status': 'COMPLETED',
                        'message': 'Payment verified successfully'
                    }
                elif status == 'failed':
                    return {
                        'success': False,
                        'status': 'FAILED',
                        'message': 'Payment failed'
                    }
                else:
                    return {
                        'success': False,
                        'status': 'PENDING',
                        'message': f'Payment status: {status}'
                    }
            else:
                return {
                    'success': False,
                    'status': 'PENDING',
                    'message': result.get('message', 'Payment verification pending')
                }
        except Exception as e:
            logger.error(f"Exception verifying Flutterwave payment: {str(e)}")
            return {
                'success': False,
                'status': 'PENDING',
                'message': f'Verification error: {str(e)}'
            }
    
    def _verify_paystack_payment(self, deposit):
        """Verify Paystack payment status using PaystackService"""
        try:
            result = self.paystack_service.verify_payment(deposit.transaction_id)
            
            if result['success']:
                status = result.get('status', '').lower()
                if status == 'success':
                    return {
                        'success': True,
                        'status': 'COMPLETED',
                        'message': 'Payment verified successfully'
                    }
                elif status == 'failed':
                    return {
                        'success': False,
                        'status': 'FAILED',
                        'message': 'Payment failed'
                    }
                else:
                    return {
                        'success': False,
                        'status': 'PENDING',
                        'message': f'Payment status: {status}'
                    }
            else:
                return {
                    'success': False,
                    'status': 'PENDING',
                    'message': result.get('message', 'Could not verify payment')
                }
        except Exception as e:
            logger.error(f"Exception verifying Paystack payment: {str(e)}")
            return {
                'success': False,
                'status': 'PENDING',
                'message': f'Verification error: {str(e)}'
            }


# Backward compatibility alias
PaymentService = PaymentManager
