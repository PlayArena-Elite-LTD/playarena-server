"""
Flutterwave Payment Service

Handles all Flutterwave payment gateway operations including:
- Payment initialization
- Payment verification
- Webhook signature verification
- Webhook event handling
"""

import logging
import requests
import hashlib
import hmac
import json
from decimal import Decimal
from django.conf import settings

logger = logging.getLogger(__name__)


class FlutterwaveService:
    """Service class for Flutterwave payment gateway operations"""
    
    def __init__(self):
        """Initialize Flutterwave service with API keys from settings"""
        self.secret_key = settings.FLUTTERWAVE_SECRET_KEY
        self.public_key = settings.FLUTTERWAVE_PUBLIC_KEY
        self.webhook_secret = settings.FLUTTERWAVE_WEBHOOK_SECRET
        self.base_url = "https://api.flutterwave.com/v3"
        
        if not self.secret_key:
            logger.warning("Flutterwave secret key not configured")
        if not self.public_key:
            logger.warning("Flutterwave public key not configured")
    
    def _get_headers(self):
        """Get headers for Flutterwave API requests"""
        return {
            "Authorization": f"Bearer {self.secret_key}",
            "Content-Type": "application/json"
        }
    
    def initialize_payment(self, amount, email, tx_ref, redirect_url=None, customer_name=None, currency="NGN", metadata=None):
        """
        Initialize a Flutterwave payment transaction
        
        Args:
            amount: Payment amount (Decimal or float)
            email: Customer email address
            tx_ref: Unique transaction reference
            redirect_url: URL to redirect after payment (optional)
            customer_name: Customer name (optional)
            currency: Currency code (default: NGN)
            metadata: Additional metadata dict (optional)
        
        Returns:
            dict: {
                'success': bool,
                'payment_link': str,
                'tx_ref': str,
                'flw_ref': str,
                'message': str
            }
        """
        if not self.secret_key:
            return {
                'success': False,
                'payment_link': None,
                'tx_ref': None,
                'flw_ref': None,
                'message': 'Flutterwave not configured'
            }
        
        try:
            url = f"{self.base_url}/payments"
            payload = {
                "tx_ref": tx_ref,
                "amount": str(float(amount)),
                "currency": currency,
                "payment_options": "card,account,banktransfer,ussd,mobilemoneyghana,mobilemoneyrwanda,mobilemoneyuganda,mobilemoneyzambia,barter,mpesa,mobilemoneyfranco,flutterwave",
                "redirect_url": redirect_url or "",
                "customer": {
                    "email": email,
                    "name": customer_name or email.split('@')[0]
                }
            }
            
            if metadata:
                payload["meta"] = metadata
            
            response = requests.post(url, json=payload, headers=self._get_headers())
            response_data = response.json()
            
            if response_data.get('status') == 'success' and response_data.get('data'):
                data = response_data['data']
                return {
                    'success': True,
                    'payment_link': data.get('link'),
                    'tx_ref': data.get('tx_ref'),
                    'flw_ref': data.get('flw_ref'),
                    'message': 'Payment initialized successfully'
                }
            else:
                error_message = response_data.get('message', 'Unknown error')
                logger.error(f"Flutterwave payment initialization failed: {error_message}")
                return {
                    'success': False,
                    'payment_link': None,
                    'tx_ref': None,
                    'flw_ref': None,
                    'message': error_message
                }
        except Exception as e:
            logger.error(f"Exception initializing Flutterwave payment: {str(e)}")
            return {
                'success': False,
                'payment_link': None,
                'tx_ref': None,
                'flw_ref': None,
                'message': f'Error: {str(e)}'
            }
    
    def verify_payment(self, transaction_id):
        """
        Verify a Flutterwave payment transaction
        
        Args:
            transaction_id: Transaction ID or transaction reference to verify
        
        Returns:
            dict: {
                'success': bool,
                'status': str (successful, failed, pending),
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
                'message': 'Flutterwave not configured'
            }
        
        try:
            # Flutterwave uses transaction ID for verification
            url = f"{self.base_url}/transactions/{transaction_id}/verify"
            response = requests.get(url, headers=self._get_headers())
            response_data = response.json()
            
            if response_data.get('status') == 'success' and response_data.get('data'):
                data = response_data['data']
                amount = Decimal(data.get('amount', 0))
                
                return {
                    'success': True,
                    'status': data.get('status'),  # successful, failed, pending
                    'amount': amount,
                    'currency': data.get('currency', 'NGN'),
                    'customer_email': data.get('customer', {}).get('email'),
                    'transaction_date': data.get('created_at'),
                    'flw_ref': data.get('flw_ref'),
                    'tx_ref': data.get('tx_ref'),
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
            logger.error(f"Exception verifying Flutterwave payment: {str(e)}")
            return {
                'success': False,
                'status': 'pending',
                'message': f'Verification error: {str(e)}'
            }
    
    def verify_webhook(self, payload, signature):
        """
        Verify Flutterwave webhook signature
        
        Args:
            payload: Raw request body (bytes or string)
            signature: X-Flutterwave-Signature header value
        
        Returns:
            bool: True if signature is valid
        """
        if not self.webhook_secret:
            logger.warning("Flutterwave webhook secret not configured")
            return False
        
        try:
            # Flutterwave uses HMAC SHA256
            if isinstance(payload, bytes):
                payload_str = payload.decode('utf-8')
            else:
                payload_str = payload
            
            computed_signature = hmac.new(
                self.webhook_secret.encode('utf-8'),
                payload_str.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()
            
            return hmac.compare_digest(computed_signature, signature)
        except Exception as e:
            logger.error(f"Error verifying Flutterwave webhook signature: {str(e)}")
            return False
    
    def handle_webhook_event(self, event_data):
        """
        Handle Flutterwave webhook event
        
        Args:
            event_data: Webhook event data dict
        
        Returns:
            dict: {
                'event_type': str,
                'tx_ref': str,
                'flw_ref': str,
                'status': str,
                'amount': Decimal,
                'message': str
            }
        """
        try:
            event_type = event_data.get('event')
            data = event_data.get('data', {})
            tx_ref = data.get('tx_ref')
            flw_ref = data.get('flw_ref')
            
            if event_type == 'charge.completed':
                status = data.get('status', '')
                amount = Decimal(data.get('amount', 0))
                
                if status == 'successful':
                    return {
                        'event_type': 'charge.completed',
                        'tx_ref': tx_ref,
                        'flw_ref': flw_ref,
                        'status': 'successful',
                        'amount': amount,
                        'message': 'Payment successful'
                    }
                else:
                    return {
                        'event_type': 'charge.completed',
                        'tx_ref': tx_ref,
                        'flw_ref': flw_ref,
                        'status': 'failed',
                        'amount': amount,
                        'message': f'Payment failed: {status}'
                    }
            elif event_type == 'charge.failed':
                return {
                    'event_type': 'charge.failed',
                    'tx_ref': tx_ref,
                    'flw_ref': flw_ref,
                    'status': 'failed',
                    'amount': Decimal(0),
                    'message': 'Payment failed'
                }
            else:
                return {
                    'event_type': event_type,
                    'tx_ref': tx_ref,
                    'flw_ref': flw_ref,
                    'status': 'unknown',
                    'amount': Decimal(0),
                    'message': f'Unknown event type: {event_type}'
                }
        except Exception as e:
            logger.error(f"Error handling Flutterwave webhook event: {str(e)}")
            return {
                'event_type': 'error',
                'tx_ref': None,
                'flw_ref': None,
                'status': 'error',
                'amount': Decimal(0),
                'message': f'Error processing webhook: {str(e)}'
            }
