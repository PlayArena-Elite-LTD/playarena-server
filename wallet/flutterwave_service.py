"""
Flutterwave Payment Service

Handles all Flutterwave payment gateway operations including:
- Payment initialization
- Payment verification
- Transfer/withdrawal operations
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
    
    def create_transfer_beneficiary(self, account_number, bank_code, account_name, email=None, currency='NGN', account_bank=None):
        """
        Create a transfer beneficiary (bank account, mobile money, etc.)
        
        Args:
            account_number: Account number or mobile money number
            bank_code: Bank code (for bank transfers) or network code (for mobile money)
            account_name: Account holder name
            email: Beneficiary email (optional)
            currency: Currency code (default: NGN)
            account_bank: Bank name (optional, can be derived from bank_code)
        
        Returns:
            dict: {
                'success': bool,
                'beneficiary_id': int,
                'account_number': str,
                'account_name': str,
                'bank_code': str,
                'bank_name': str,
                'message': str
            }
        """
        if not self.secret_key:
            return {
                'success': False,
                'beneficiary_id': None,
                'account_number': None,
                'account_name': None,
                'bank_code': None,
                'bank_name': None,
                'message': 'Flutterwave not configured'
            }
        
        try:
            url = f"{self.base_url}/beneficiaries"
            payload = {
                "account_number": account_number,
                "bank_code": bank_code,
                "account_name": account_name,
                "currency": currency,
            }
            
            if email:
                payload["email"] = email
            
            if account_bank:
                payload["account_bank"] = account_bank
            
            response = requests.post(url, json=payload, headers=self._get_headers())
            response_data = response.json()
            
            if response_data.get('status') == 'success' and response_data.get('data'):
                data = response_data['data']
                return {
                    'success': True,
                    'beneficiary_id': data.get('id'),
                    'account_number': data.get('account_number'),
                    'account_name': data.get('account_name'),
                    'bank_code': data.get('bank_code'),
                    'bank_name': data.get('bank_name'),
                    'message': 'Transfer beneficiary created successfully'
                }
            else:
                error_message = response_data.get('message', 'Unknown error')
                logger.error(f"Flutterwave transfer beneficiary creation failed: {error_message}")
                return {
                    'success': False,
                    'beneficiary_id': None,
                    'account_number': None,
                    'account_name': None,
                    'bank_code': None,
                    'bank_name': None,
                    'message': error_message
                }
        except Exception as e:
            logger.error(f"Exception creating Flutterwave transfer beneficiary: {str(e)}")
            return {
                'success': False,
                'beneficiary_id': None,
                'account_number': None,
                'account_name': None,
                'bank_code': None,
                'bank_name': None,
                'message': f'Error: {str(e)}'
            }
    
    def initiate_transfer(self, amount, beneficiary_id, reference=None, narration=None, currency='NGN'):
        """
        Initiate a transfer to a beneficiary
        
        Args:
            amount: Transfer amount (Decimal or float)
            beneficiary_id: Beneficiary ID from create_transfer_beneficiary
            reference: Unique transfer reference (optional, auto-generated if not provided)
            narration: Transfer narration/description (optional)
            currency: Currency code (default: NGN)
        
        Returns:
            dict: {
                'success': bool,
                'transfer_id': int,
                'reference': str,
                'amount': Decimal,
                'status': str,
                'message': str
            }
        """
        if not self.secret_key:
            return {
                'success': False,
                'transfer_id': None,
                'reference': None,
                'amount': None,
                'status': None,
                'message': 'Flutterwave not configured'
            }
        
        try:
            url = f"{self.base_url}/transfers"
            payload = {
                "account_bank": "flutterwave",  # Transfer from Flutterwave balance
                "account_number": str(beneficiary_id),  # Using beneficiary_id
                "amount": str(float(amount)),
                "narration": narration or f"Withdrawal - {reference or 'N/A'}",
                "currency": currency,
                "beneficiary_id": beneficiary_id,
            }
            
            if reference:
                payload["reference"] = reference
            
            response = requests.post(url, json=payload, headers=self._get_headers())
            response_data = response.json()
            
            if response_data.get('status') == 'success' and response_data.get('data'):
                data = response_data['data']
                transfer_amount = Decimal(str(data.get('amount', 0)))
                
                return {
                    'success': True,
                    'transfer_id': data.get('id'),
                    'reference': data.get('reference'),
                    'amount': transfer_amount,
                    'status': data.get('status'),  # NEW, PENDING, SUCCESSFUL, FAILED
                    'message': 'Transfer initiated successfully'
                }
            else:
                error_message = response_data.get('message', 'Unknown error')
                logger.error(f"Flutterwave transfer initiation failed: {error_message}")
                return {
                    'success': False,
                    'transfer_id': None,
                    'reference': None,
                    'amount': None,
                    'status': None,
                    'message': error_message
                }
        except Exception as e:
            logger.error(f"Exception initiating Flutterwave transfer: {str(e)}")
            return {
                'success': False,
                'transfer_id': None,
                'reference': None,
                'amount': None,
                'status': None,
                'message': f'Error: {str(e)}'
            }
    
    def verify_transfer(self, transfer_id=None, reference=None):
        """
        Verify a transfer status
        
        Args:
            transfer_id: Transfer ID from initiate_transfer (preferred)
            reference: Transfer reference (alternative if transfer_id not available)
        
        Returns:
            dict: {
                'success': bool,
                'status': str (NEW, PENDING, SUCCESSFUL, FAILED),
                'amount': Decimal,
                'beneficiary_id': int,
                'transfer_id': int,
                'reference': str,
                'message': str
            }
        """
        if not self.secret_key:
            return {
                'success': False,
                'status': 'pending',
                'message': 'Flutterwave not configured'
            }
        
        if not transfer_id and not reference:
            return {
                'success': False,
                'status': 'pending',
                'message': 'Either transfer_id or reference is required'
            }
        
        try:
            # Use transfer_id if available, otherwise use reference
            if transfer_id:
                url = f"{self.base_url}/transfers/{transfer_id}"
            else:
                # Flutterwave allows querying by reference
                url = f"{self.base_url}/transfers?reference={reference}"
            
            response = requests.get(url, headers=self._get_headers())
            response_data = response.json()
            
            if response_data.get('status') == 'success' and response_data.get('data'):
                data = response_data['data']
                # Handle both single object and list responses
                if isinstance(data, list) and len(data) > 0:
                    data = data[0]
                
                transfer_amount = Decimal(str(data.get('amount', 0)))
                status = data.get('status', '').upper()
                
                # Normalize status to lowercase for consistency
                status_map = {
                    'NEW': 'pending',
                    'PENDING': 'pending',
                    'SUCCESSFUL': 'success',
                    'FAILED': 'failed'
                }
                normalized_status = status_map.get(status, status.lower())
                
                return {
                    'success': True,
                    'status': normalized_status,
                    'amount': transfer_amount,
                    'beneficiary_id': data.get('beneficiary_id'),
                    'transfer_id': data.get('id'),
                    'reference': data.get('reference'),
                    'message': 'Transfer verified successfully'
                }
            else:
                error_message = response_data.get('message', 'Unknown error')
                return {
                    'success': False,
                    'status': 'pending',
                    'message': error_message
                }
        except Exception as e:
            logger.error(f"Exception verifying Flutterwave transfer: {str(e)}")
            return {
                'success': False,
                'status': 'pending',
                'message': f'Verification error: {str(e)}'
            }