"""
Payment Manager for handling payment gateway integrations.

This module provides a unified interface for processing deposits and withdrawals
through multiple payment gateways (Paystack, Flutterwave, etc.).

Security features:
- API key management
- Error handling and logging
- Transaction tracking
- Retry logic support
"""

import logging
import requests
from decimal import Decimal
from typing import Dict, Optional, Any
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


class PaymentManager:
    """
    Unified payment gateway manager for processing deposits and withdrawals.
    
    Supports multiple payment gateways:
    - Paystack
    - Flutterwave
    - Bank Transfer (manual processing)
    - Mobile Money
    """
    
    def __init__(self):
        """Initialize PaymentManager with gateway configurations"""
        # Paystack configuration
        self.paystack_secret_key = getattr(settings, 'PAYSTACK_SECRET_KEY', None)
        self.paystack_public_key = getattr(settings, 'PAYSTACK_PUBLIC_KEY', None)
        self.paystack_base_url = getattr(settings, 'PAYSTACK_BASE_URL', 'https://api.paystack.co')
        
        # Flutterwave configuration
        self.flutterwave_secret_key = getattr(settings, 'FLUTTERWAVE_SECRET_KEY', None)
        self.flutterwave_public_key = getattr(settings, 'FLUTTERWAVE_PUBLIC_KEY', None)
        self.flutterwave_base_url = getattr(settings, 'FLUTTERWAVE_BASE_URL', 'https://api.flutterwave.com/v3')
        
        # General settings
        self.test_mode = getattr(settings, 'PAYMENT_GATEWAY_TEST_MODE', True)
    
    def initialize_deposit(self, deposit, callback_url: Optional[str] = None) -> Dict[str, Any]:
        """
        Initialize a deposit payment through the appropriate payment gateway.
        
        This method creates a payment request with the gateway and returns
        the authorization URL or payment details needed to complete the deposit.
        
        Args:
            deposit: Deposit model instance
            callback_url: Optional callback URL for payment completion
            
        Returns:
            dict: {
                'success': bool,
                'authorization_url': str or None,
                'payment_reference': str or None,
                'gateway_response': dict,
                'failure_reason': str or None
            }
        """
        payment_method = deposit.payment_method
        
        try:
            if payment_method == 'STRIPE':
                return self._initialize_stripe_deposit(deposit, callback_url)
            elif payment_method == 'MOBILE_MONEY':
                return self._initialize_mobile_money_deposit(deposit, callback_url)
            elif payment_method == 'BANK_TRANSFER':
                return self._initialize_bank_transfer_deposit(deposit, callback_url)
            elif payment_method == 'PAYPAL':
                return self._initialize_paypal_deposit(deposit, callback_url)
            else:
                return {
                    'success': False,
                    'authorization_url': None,
                    'payment_reference': None,
                    'gateway_response': {'status': 'error', 'message': 'Unsupported payment method'},
                    'failure_reason': f'Payment method {payment_method} is not supported'
                }
        except Exception as e:
            logger.error(
                f'Error initializing deposit {deposit.id}: {str(e)}',
                exc_info=True
            )
            return {
                'success': False,
                'authorization_url': None,
                'payment_reference': None,
                'gateway_response': {'status': 'error', 'error': str(e)},
                'failure_reason': f'Processing error: {str(e)}'
            }
    
    def process_withdrawal(self, withdrawal) -> Dict[str, Any]:
        """
        Process a withdrawal through the appropriate payment gateway.
        
        Args:
            withdrawal: Withdrawal model instance
            
        Returns:
            dict: {
                'success': bool,
                'transaction_id': str or None,
                'gateway_response': dict,
                'failure_reason': str or None
            }
        """
        payment_method = withdrawal.payment_method
        
        try:
            if payment_method == 'BANK_TRANSFER':
                return self._process_bank_transfer(withdrawal)
            elif payment_method == 'MOBILE_MONEY':
                return self._process_mobile_money(withdrawal)
            elif payment_method == 'PAYPAL':
                return self._process_paypal(withdrawal)
            elif payment_method == 'STRIPE':
                return self._process_stripe(withdrawal)
            else:
                return {
                    'success': False,
                    'transaction_id': None,
                    'gateway_response': {'status': 'error', 'message': 'Unsupported payment method'},
                    'failure_reason': f'Payment method {payment_method} is not supported'
                }
        except Exception as e:
            logger.error(
                f'Error processing withdrawal {withdrawal.id}: {str(e)}',
                exc_info=True
            )
            return {
                'success': False,
                'transaction_id': None,
                'gateway_response': {'status': 'error', 'error': str(e)},
                'failure_reason': f'Processing error: {str(e)}'
            }
    
    def _process_bank_transfer(self, withdrawal) -> Dict[str, Any]:
        """
        Process bank transfer withdrawal.
        
        For now, this is a placeholder that simulates processing.
        In production, this would integrate with bank APIs or manual processing workflow.
        """
        logger.info(f'Processing bank transfer for withdrawal {withdrawal.id}')
        
        # TODO: Integrate with actual bank transfer API when available
        # For now, simulate processing (manual approval required)
        
        transaction_id = f"BANK_{withdrawal.id}_{int(timezone.now().timestamp())}"
        
        return {
            'success': True,
            'transaction_id': transaction_id,
            'gateway_response': {
                'status': 'pending',
                'message': 'Bank transfer initiated. Processing may take 1-3 business days.',
                'transaction_id': transaction_id,
                'gateway': 'bank_transfer',
                'processed_at': timezone.now().isoformat()
            },
            'failure_reason': None
        }
    
    def _process_mobile_money(self, withdrawal) -> Dict[str, Any]:
        """
        Process mobile money withdrawal via Paystack or Flutterwave.
        
        Priority: Paystack > Flutterwave
        """
        # Try Paystack first if configured
        if self.paystack_secret_key:
            result = self._process_paystack_transfer(withdrawal)
            if result['success']:
                return result
            # If Paystack fails, try Flutterwave as fallback
            if self.flutterwave_secret_key:
                logger.info(f'Paystack failed for withdrawal {withdrawal.id}, trying Flutterwave')
                return self._process_flutterwave_transfer(withdrawal)
            return result
        
        # Try Flutterwave if Paystack not configured
        if self.flutterwave_secret_key:
            return self._process_flutterwave_transfer(withdrawal)
        
        # No gateway configured
        return {
            'success': False,
            'transaction_id': None,
            'gateway_response': {'status': 'error', 'message': 'No mobile money gateway configured'},
            'failure_reason': 'Mobile money payment gateway not configured'
        }
    
    def _process_paypal(self, withdrawal) -> Dict[str, Any]:
        """
        Process PayPal withdrawal.
        
        TODO: Integrate with PayPal Payouts API when available
        """
        logger.warning(f'PayPal withdrawal processing not yet implemented for withdrawal {withdrawal.id}')
        
        return {
            'success': False,
            'transaction_id': None,
            'gateway_response': {'status': 'error', 'message': 'PayPal integration not yet available'},
            'failure_reason': 'PayPal withdrawal processing is not yet implemented'
        }
    
    def _process_stripe(self, withdrawal) -> Dict[str, Any]:
        """
        Process Stripe withdrawal.
        
        TODO: Integrate with Stripe Payouts API when available
        """
        logger.warning(f'Stripe withdrawal processing not yet implemented for withdrawal {withdrawal.id}')
        
        return {
            'success': False,
            'transaction_id': None,
            'gateway_response': {'status': 'error', 'message': 'Stripe integration not yet available'},
            'failure_reason': 'Stripe withdrawal processing is not yet implemented'
        }
    
    def _process_paystack_transfer(self, withdrawal) -> Dict[str, Any]:
        """
        Process withdrawal via Paystack Transfer API.
        
        Documentation: https://paystack.com/docs/api/transfer/
        """
        if not self.paystack_secret_key:
            return {
                'success': False,
                'transaction_id': None,
                'gateway_response': {'status': 'error', 'message': 'Paystack not configured'},
                'failure_reason': 'Paystack secret key not configured'
            }
        
        try:
            # Extract account details (format: account_number, bank_code, account_name)
            # For mobile money: phone number, provider code
            account_details = withdrawal.account_details.strip()
            
            # Parse account details (assumes format: "account_number|bank_code" or "phone|provider")
            # This is a simplified parser - adjust based on your account_details format
            parts = account_details.split('|')
            if len(parts) < 2:
                return {
                    'success': False,
                    'transaction_id': None,
                    'gateway_response': {'status': 'error', 'message': 'Invalid account details format'},
                    'failure_reason': 'Account details must be in format: account_number|bank_code or phone|provider'
                }
            
            recipient_code = parts[0].strip()
            bank_code = parts[1].strip() if len(parts) > 1 else None
            
            # Prepare transfer request
            amount_in_kobo = int(float(withdrawal.amount) * 100)  # Paystack uses kobo (smallest currency unit)
            
            transfer_data = {
                'source': 'balance',  # Transfer from account balance
                'amount': amount_in_kobo,
                'recipient': recipient_code,  # Recipient code (must be created first via recipient API)
                'reason': f'Withdrawal for {withdrawal.user.username}',
                'reference': f'WDR_{withdrawal.id}_{int(timezone.now().timestamp())}'
            }
            
            # Make API request to Paystack
            headers = {
                'Authorization': f'Bearer {self.paystack_secret_key}',
                'Content-Type': 'application/json'
            }
            
            url = f'{self.paystack_base_url}/transfer'
            
            # In test mode, simulate the response
            if self.test_mode:
                logger.info(f'[TEST MODE] Simulating Paystack transfer for withdrawal {withdrawal.id}')
                transaction_id = f"PSK_{withdrawal.id}_{int(timezone.now().timestamp())}"
                return {
                    'success': True,
                    'transaction_id': transaction_id,
                    'gateway_response': {
                        'status': 'success',
                        'message': 'Transfer initiated successfully',
                        'transfer_code': transaction_id,
                        'gateway': 'paystack',
                        'amount': amount_in_kobo,
                        'processed_at': timezone.now().isoformat()
                    },
                    'failure_reason': None
                }
            
            # Production: Make actual API call
            response = requests.post(url, json=transfer_data, headers=headers, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            if data.get('status'):
                transaction_id = data.get('data', {}).get('transfer_code') or data.get('data', {}).get('reference')
                return {
                    'success': True,
                    'transaction_id': transaction_id,
                    'gateway_response': data.get('data', {}),
                    'failure_reason': None
                }
            else:
                error_message = data.get('message', 'Unknown error')
                return {
                    'success': False,
                    'transaction_id': None,
                    'gateway_response': data,
                    'failure_reason': f'Paystack error: {error_message}'
                }
        
        except requests.exceptions.RequestException as e:
            logger.error(f'Paystack API error for withdrawal {withdrawal.id}: {str(e)}', exc_info=True)
            return {
                'success': False,
                'transaction_id': None,
                'gateway_response': {'status': 'error', 'error': str(e)},
                'failure_reason': f'Paystack API error: {str(e)}'
            }
        except Exception as e:
            logger.error(f'Error processing Paystack transfer for withdrawal {withdrawal.id}: {str(e)}', exc_info=True)
            return {
                'success': False,
                'transaction_id': None,
                'gateway_response': {'status': 'error', 'error': str(e)},
                'failure_reason': f'Processing error: {str(e)}'
            }
    
    def _process_flutterwave_transfer(self, withdrawal) -> Dict[str, Any]:
        """
        Process withdrawal via Flutterwave Transfer API.
        
        Documentation: https://developer.flutterwave.com/docs/transfers
        """
        if not self.flutterwave_secret_key:
            return {
                'success': False,
                'transaction_id': None,
                'gateway_response': {'status': 'error', 'message': 'Flutterwave not configured'},
                'failure_reason': 'Flutterwave secret key not configured'
            }
        
        try:
            # Extract account details
            account_details = withdrawal.account_details.strip()
            parts = account_details.split('|')
            if len(parts) < 2:
                return {
                    'success': False,
                    'transaction_id': None,
                    'gateway_response': {'status': 'error', 'message': 'Invalid account details format'},
                    'failure_reason': 'Account details must be in format: account_number|bank_code or phone|provider'
                }
            
            account_number = parts[0].strip()
            bank_code = parts[1].strip()
            
            # Prepare transfer request
            amount = float(withdrawal.amount)
            
            transfer_data = {
                'account_bank': bank_code,
                'account_number': account_number,
                'amount': amount,
                'narration': f'Withdrawal for {withdrawal.user.username}',
                'currency': 'NGN',  # Default to NGN, make configurable
                'reference': f'WDR_{withdrawal.id}_{int(timezone.now().timestamp())}',
                'callback_url': getattr(settings, 'FLUTTERWAVE_WEBHOOK_URL', None)
            }
            
            # Make API request to Flutterwave
            headers = {
                'Authorization': f'Bearer {self.flutterwave_secret_key}',
                'Content-Type': 'application/json'
            }
            
            url = f'{self.flutterwave_base_url}/transfers'
            
            # In test mode, simulate the response
            if self.test_mode:
                logger.info(f'[TEST MODE] Simulating Flutterwave transfer for withdrawal {withdrawal.id}')
                transaction_id = f"FLW_{withdrawal.id}_{int(timezone.now().timestamp())}"
                return {
                    'success': True,
                    'transaction_id': transaction_id,
                    'gateway_response': {
                        'status': 'success',
                        'message': 'Transfer initiated successfully',
                        'id': transaction_id,
                        'gateway': 'flutterwave',
                        'amount': amount,
                        'processed_at': timezone.now().isoformat()
                    },
                    'failure_reason': None
                }
            
            # Production: Make actual API call
            response = requests.post(url, json=transfer_data, headers=headers, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            if data.get('status') == 'success':
                transaction_id = data.get('data', {}).get('id') or data.get('data', {}).get('reference')
                return {
                    'success': True,
                    'transaction_id': transaction_id,
                    'gateway_response': data.get('data', {}),
                    'failure_reason': None
                }
            else:
                error_message = data.get('message', 'Unknown error')
                return {
                    'success': False,
                    'transaction_id': None,
                    'gateway_response': data,
                    'failure_reason': f'Flutterwave error: {error_message}'
                }
        
        except requests.exceptions.RequestException as e:
            logger.error(f'Flutterwave API error for withdrawal {withdrawal.id}: {str(e)}', exc_info=True)
            return {
                'success': False,
                'transaction_id': None,
                'gateway_response': {'status': 'error', 'error': str(e)},
                'failure_reason': f'Flutterwave API error: {str(e)}'
            }
        except Exception as e:
            logger.error(f'Error processing Flutterwave transfer for withdrawal {withdrawal.id}: {str(e)}', exc_info=True)
            return {
                'success': False,
                'transaction_id': None,
                'gateway_response': {'status': 'error', 'error': str(e)},
                'failure_reason': f'Processing error: {str(e)}'
            }


# Singleton instance
_payment_manager = None


def get_payment_manager() -> PaymentManager:
    """Get or create PaymentManager singleton instance"""
    global _payment_manager
    if _payment_manager is None:
        _payment_manager = PaymentManager()
    return _payment_manager

