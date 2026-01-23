"""
Payment Service Module for Flutterwave and Paystack Integration

This module provides a unified interface for processing payments through
Flutterwave and Paystack payment gateways.
"""

import logging
from decimal import Decimal
from django.conf import settings
from django.urls import reverse

logger = logging.getLogger(__name__)


class PaymentService:
    """Unified payment service for Flutterwave and Paystack"""
    
    def __init__(self):
        """Initialize payment service with API keys from settings"""
        self.flutterwave_public_key = settings.FLUTTERWAVE_PUBLIC_KEY
        self.flutterwave_secret_key = settings.FLUTTERWAVE_SECRET_KEY
        self.paystack_public_key = settings.PAYSTACK_PUBLIC_KEY
        self.paystack_secret_key = settings.PAYSTACK_SECRET_KEY
    
    def _get_flutterwave_client(self):
        """Get Flutterwave Rave client instance"""
        try:
            from rave_python import Rave
            if not self.flutterwave_secret_key:
                logger.warning("Flutterwave secret key not configured")
                return None
            return Rave(self.flutterwave_public_key, self.flutterwave_secret_key, usingEnv=False)
        except ImportError:
            logger.error("Flutterwave SDK (rave-python) not installed")
            return None
        except Exception as e:
            logger.error(f"Error initializing Flutterwave client: {str(e)}")
            return None
    
    def _get_paystack_client(self):
        """Get Paystack client instance"""
        try:
            import paystackpy
            if not self.paystack_secret_key:
                logger.warning("Paystack secret key not configured")
                return None
            # Paystackpy uses a different initialization
            # We'll use direct API calls with requests
            return {
                'public_key': self.paystack_public_key,
                'secret_key': self.paystack_secret_key
            }
        except ImportError:
            logger.error("Paystack SDK (paystackpy) not installed")
            return None
        except Exception as e:
            logger.error(f"Error initializing Paystack client: {str(e)}")
            return None
    
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
        amount = float(deposit.amount)
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
        """Initialize Flutterwave payment"""
        rave = self._get_flutterwave_client()
        if not rave:
            return {
                'success': False,
                'payment_url': None,
                'payment_reference': None,
                'message': 'Flutterwave not configured',
                'gateway': 'FLUTTERWAVE'
            }
        
        try:
            # Build callback URLs
            success_url = request.build_absolute_uri(reverse('payment_success', kwargs={'deposit_id': deposit.id}))
            cancel_url = request.build_absolute_uri(reverse('payment_cancel', kwargs={'deposit_id': deposit.id}))
            
            # Create payment payload
            payload = {
                "amount": amount,
                "currency": "USD",
                "payment_method": "both",  # card, account, both
                "customer": {
                    "email": user.email,
                    "name": user.get_full_name() or user.username,
                },
                "meta": {
                    "deposit_id": deposit.id,
                    "user_id": user.id,
                },
                "redirect_url": success_url,
                "tx_ref": f"deposit_{deposit.id}_{deposit.created_at.timestamp()}",
            }
            
            # Initialize payment
            response = rave.Payment.charge(payload)
            
            if response and response.get('status') == 'success':
                payment_data = response.get('data', {})
                payment_link = payment_data.get('link')
                tx_ref = payload['tx_ref']
                
                # Update deposit with transaction reference
                deposit.transaction_id = tx_ref
                deposit.status = 'PROCESSING'
                deposit.save(update_fields=['transaction_id', 'status'])
                
                logger.info(f"Flutterwave payment initialized for deposit {deposit.id}: {tx_ref}")
                
                return {
                    'success': True,
                    'payment_url': payment_link,
                    'payment_reference': tx_ref,
                    'message': 'Payment initialized successfully',
                    'gateway': 'FLUTTERWAVE'
                }
            else:
                error_message = response.get('message', 'Unknown error') if response else 'No response from Flutterwave'
                logger.error(f"Flutterwave payment initialization failed: {error_message}")
                return {
                    'success': False,
                    'payment_url': None,
                    'payment_reference': None,
                    'message': f'Flutterwave error: {error_message}',
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
        """Initialize Paystack payment"""
        paystack_config = self._get_paystack_client()
        if not paystack_config:
            return {
                'success': False,
                'payment_url': None,
                'payment_reference': None,
                'message': 'Paystack not configured',
                'gateway': 'PAYSTACK'
            }
        
        try:
            import requests
            
            # Build callback URL
            callback_url = request.build_absolute_uri(reverse('payment_success', kwargs={'deposit_id': deposit.id}))
            
            # Create payment reference
            payment_reference = f"deposit_{deposit.id}_{deposit.created_at.timestamp()}"
            
            # Paystack API endpoint
            url = "https://api.paystack.co/transaction/initialize"
            headers = {
                "Authorization": f"Bearer {paystack_config['secret_key']}",
                "Content-Type": "application/json"
            }
            payload = {
                "email": user.email,
                "amount": int(amount * 100),  # Paystack amounts in kobo (cents)
                "currency": "USD",
                "reference": payment_reference,
                "callback_url": callback_url,
                "metadata": {
                    "deposit_id": deposit.id,
                    "user_id": user.id,
                }
            }
            
            # Make API request
            response = requests.post(url, json=payload, headers=headers)
            response_data = response.json()
            
            if response_data.get('status') and response_data.get('data'):
                payment_url = response_data['data'].get('authorization_url')
                
                # Update deposit with transaction reference
                deposit.transaction_id = payment_reference
                deposit.status = 'PROCESSING'
                deposit.save(update_fields=['transaction_id', 'status'])
                
                logger.info(f"Paystack payment initialized for deposit {deposit.id}: {payment_reference}")
                
                return {
                    'success': True,
                    'payment_url': payment_url,
                    'payment_reference': payment_reference,
                    'message': 'Payment initialized successfully',
                    'gateway': 'PAYSTACK'
                }
            else:
                error_message = response_data.get('message', 'Unknown error')
                logger.error(f"Paystack payment initialization failed: {error_message}")
                return {
                    'success': False,
                    'payment_url': None,
                    'payment_reference': None,
                    'message': f'Paystack error: {error_message}',
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
        """Verify Flutterwave payment status"""
        rave = self._get_flutterwave_client()
        if not rave:
            return {
                'success': False,
                'status': 'PENDING',
                'message': 'Flutterwave not configured'
            }
        
        try:
            # Verify transaction using transaction reference
            response = rave.Transfer.getTransfer(deposit.transaction_id)
            # Actually, for payments we should use Payment.verify
            # Let me use the correct method
            response = rave.Payment.verify(deposit.transaction_id)
            
            if response and response.get('status') == 'success':
                data = response.get('data', {})
                charge_code = data.get('chargecode', '')
                
                if charge_code == '00' or data.get('status') == 'successful':
                    return {
                        'success': True,
                        'status': 'COMPLETED',
                        'message': 'Payment verified successfully'
                    }
                else:
                    return {
                        'success': False,
                        'status': 'FAILED',
                        'message': f"Payment failed: {data.get('status', 'Unknown')}"
                    }
            else:
                return {
                    'success': False,
                    'status': 'PENDING',
                    'message': 'Payment verification pending'
                }
        except Exception as e:
            logger.error(f"Exception verifying Flutterwave payment: {str(e)}")
            return {
                'success': False,
                'status': 'PENDING',
                'message': f'Verification error: {str(e)}'
            }
    
    def _verify_paystack_payment(self, deposit):
        """Verify Paystack payment status"""
        paystack_config = self._get_paystack_client()
        if not paystack_config:
            return {
                'success': False,
                'status': 'PENDING',
                'message': 'Paystack not configured'
            }
        
        try:
            import requests
            
            # Paystack verification endpoint
            url = f"https://api.paystack.co/transaction/verify/{deposit.transaction_id}"
            headers = {
                "Authorization": f"Bearer {paystack_config['secret_key']}"
            }
            
            response = requests.get(url, headers=headers)
            response_data = response.json()
            
            if response_data.get('status') and response_data.get('data'):
                transaction_data = response_data['data']
                status = transaction_data.get('status')
                
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
                    'message': 'Could not verify payment'
                }
        except Exception as e:
            logger.error(f"Exception verifying Paystack payment: {str(e)}")
            return {
                'success': False,
                'status': 'PENDING',
                'message': f'Verification error: {str(e)}'
            }
