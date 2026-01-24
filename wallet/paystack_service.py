"""
Paystack Payment Service

Handles all Paystack payment gateway operations including:
- Payment initialization
- Payment verification
- Webhook signature verification
- Webhook event handling
"""

import logging
import requests
import hashlib
import hmac
from decimal import Decimal
from django.conf import settings

logger = logging.getLogger(__name__)


class PaystackService:
    """Service class for Paystack payment gateway operations"""
    
    def __init__(self):
        """Initialize Paystack service with API keys from settings"""
        self.secret_key = settings.PAYSTACK_SECRET_KEY
        self.public_key = settings.PAYSTACK_PUBLIC_KEY
        self.webhook_secret = settings.PAYSTACK_WEBHOOK_SECRET
        self.base_url = "https://api.paystack.co"
        
        if not self.secret_key:
            logger.warning("Paystack secret key not configured")
        if not self.public_key:
            logger.warning("Paystack public key not configured")
    
    def _get_headers(self):
        """Get headers for Paystack API requests"""
        return {
            "Authorization": f"Bearer {self.secret_key}",
            "Content-Type": "application/json"
        }
    
    def initialize_payment(self, amount, email, reference, callback_url=None, metadata=None):
        """
        Initialize a Paystack payment transaction
        
        Args:
            amount: Payment amount (Decimal or float)
            email: Customer email address
            reference: Unique payment reference
            callback_url: URL to redirect after payment (optional)
            metadata: Additional metadata dict (optional)
        
        Returns:
            dict: {
                'success': bool,
                'authorization_url': str,
                'access_code': str,
                'reference': str,
                'message': str
            }
        """
        if not self.secret_key:
            return {
                'success': False,
                'authorization_url': None,
                'access_code': None,
                'reference': None,
                'message': 'Paystack not configured'
            }
        
        try:
            # Convert amount to kobo (Paystack uses smallest currency unit)
            # For USD, multiply by 100 to get cents
            amount_in_kobo = int(float(amount) * 100)
            
            url = f"{self.base_url}/transaction/initialize"
            payload = {
                "email": email,
                "amount": amount_in_kobo,
                "reference": reference,
            }
            
            if callback_url:
                payload["callback_url"] = callback_url
            
            if metadata:
                payload["metadata"] = metadata
            
            response = requests.post(url, json=payload, headers=self._get_headers())
            response_data = response.json()
            
            if response_data.get('status') and response_data.get('data'):
                data = response_data['data']
                return {
                    'success': True,
                    'authorization_url': data.get('authorization_url'),
                    'access_code': data.get('access_code'),
                    'reference': data.get('reference'),
                    'message': 'Payment initialized successfully'
                }
            else:
                error_message = response_data.get('message', 'Unknown error')
                logger.error(f"Paystack payment initialization failed: {error_message}")
                return {
                    'success': False,
                    'authorization_url': None,
                    'access_code': None,
                    'reference': None,
                    'message': error_message
                }
        except Exception as e:
            logger.error(f"Exception initializing Paystack payment: {str(e)}")
            return {
                'success': False,
                'authorization_url': None,
                'access_code': None,
                'reference': None,
                'message': f'Error: {str(e)}'
            }
    
    def verify_payment(self, reference):
        """
        Verify a Paystack payment transaction
        
        Args:
            reference: Payment reference to verify
        
        Returns:
            dict: {
                'success': bool,
                'status': str (success, failed, pending),
                'amount': Decimal,
                'currency': str,
                'customer_email': str,
                'transaction_date': str,
                'message': str
            }
        """
        if not self.secret_key:
            return {
                'success': False,
                'status': 'pending',
                'message': 'Paystack not configured'
            }
        
        try:
            url = f"{self.base_url}/transaction/verify/{reference}"
            response = requests.get(url, headers=self._get_headers())
            response_data = response.json()
            
            if response_data.get('status') and response_data.get('data'):
                data = response_data['data']
                amount = Decimal(data.get('amount', 0)) / 100  # Convert from kobo
                
                return {
                    'success': True,
                    'status': data.get('status'),  # success, failed, pending
                    'amount': amount,
                    'currency': data.get('currency', 'NGN'),
                    'customer_email': data.get('customer', {}).get('email'),
                    'transaction_date': data.get('transaction_date'),
                    'gateway_response': data.get('gateway_response'),
                    'message': 'Payment verified successfully'
                }
            else:
                error_message = response_data.get('message', 'Unknown error')
                return {
                    'success': False,
                    'status': 'pending',
                    'message': error_message
                }
        except Exception as e:
            logger.error(f"Exception verifying Paystack payment: {str(e)}")
            return {
                'success': False,
                'status': 'pending',
                'message': f'Verification error: {str(e)}'
            }
    
    def verify_webhook(self, payload, signature):
        """
        Verify Paystack webhook signature
        
        Args:
            payload: Raw request body (bytes or string)
            signature: X-Paystack-Signature header value
        
        Returns:
            bool: True if signature is valid
        """
        if not self.webhook_secret:
            logger.warning("Paystack webhook secret not configured")
            return False
        
        try:
            # Paystack uses HMAC SHA512
            computed_signature = hmac.new(
                self.webhook_secret.encode('utf-8'),
                payload.encode('utf-8') if isinstance(payload, str) else payload,
                hashlib.sha512
            ).hexdigest()
            
            return hmac.compare_digest(computed_signature, signature)
        except Exception as e:
            logger.error(f"Error verifying Paystack webhook signature: {str(e)}")
            return False
    
    def handle_webhook_event(self, event_data):
        """
        Handle Paystack webhook event
        
        Args:
            event_data: Webhook event data dict
        
        Returns:
            dict: {
                'event_type': str,
                'reference': str,
                'status': str,
                'amount': Decimal,
                'message': str
            }
        """
        try:
            event_type = event_data.get('event')
            data = event_data.get('data', {})
            reference = data.get('reference')
            
            if event_type == 'charge.success':
                amount = Decimal(data.get('amount', 0)) / 100
                return {
                    'event_type': 'charge.success',
                    'reference': reference,
                    'status': 'success',
                    'amount': amount,
                    'message': 'Payment successful'
                }
            elif event_type == 'charge.failed':
                return {
                    'event_type': 'charge.failed',
                    'reference': reference,
                    'status': 'failed',
                    'amount': Decimal(0),
                    'message': 'Payment failed'
                }
            else:
                return {
                    'event_type': event_type,
                    'reference': reference,
                    'status': 'unknown',
                    'amount': Decimal(0),
                    'message': f'Unknown event type: {event_type}'
                }
        except Exception as e:
            logger.error(f"Error handling Paystack webhook event: {str(e)}")
            return {
                'event_type': 'error',
                'reference': None,
                'status': 'error',
                'amount': Decimal(0),
                'message': f'Error processing webhook: {str(e)}'
            }
