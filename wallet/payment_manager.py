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
from urllib.parse import urljoin, urlparse
import ipaddress
from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from services.payments.factory import get_active_payment_provider, get_payment_gateway
from wallet.payment_debug import payment_debug_enabled, mask_secret

logger = logging.getLogger(__name__)


def _is_local_or_private_url(url: str) -> bool:
    """
    Best-effort check: is this URL clearly not publicly reachable?

    Pesapal IPN registration requires a publicly reachable URL. Localhost, loopback,
    0.0.0.0, and RFC1918 private IPs won't work.
    """
    try:
        host = (urlparse(url).hostname or "").strip().lower()
    except Exception:
        return False

    if not host:
        return False

    if host in ("localhost", "127.0.0.1", "0.0.0.0", "::1"):
        return True

    try:
        ip = ipaddress.ip_address(host)
        return bool(ip.is_private or ip.is_loopback or ip.is_link_local)
    except Exception:
        # Not an IP address (domain). Assume it *might* be public.
        return False


class PaymentManager:
    """
    Unified payment gateway manager for processing deposits and withdrawals.
    
    Supports multiple payment gateways:
    - Lipila (active — card & mobile money)
    - Bank Transfer (manual processing)
    - Mobile Money withdrawals (via Lipila disbursement when configured)
    """
    
    def __init__(self):
        """Initialize PaymentManager with gateway configurations"""
        # General settings
        self.test_mode = getattr(settings, 'PAYMENT_GATEWAY_TEST_MODE', True)
        self.bank_payout_mode = str(getattr(settings, 'BANK_PAYOUT_MODE', 'mock')).strip().lower()
        self.bank_payout_api_url = str(getattr(settings, 'BANK_PAYOUT_API_URL', '')).strip()
        self.bank_payout_api_key = str(getattr(settings, 'BANK_PAYOUT_API_KEY', '')).strip()
        self.bank_payout_timeout_seconds = int(getattr(settings, 'BANK_PAYOUT_TIMEOUT_SECONDS', 30))

    def initialize_deposit(
        self,
        deposit,
        callback_url: Optional[str] = None,
        ipn_url: Optional[str] = None,
        mobile_number: Optional[str] = None,
    ) -> Dict[str, Any]:
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
            if payment_method in ('LIPILA', 'LIPILA_MOMO'):
                return self._initialize_lipila_via_gateway(
                    deposit,
                    callback_url,
                    mobile_number=mobile_number,
                )
            elif payment_method == 'BANK_TRANSFER':
                return self._initialize_bank_transfer_deposit(deposit, callback_url)
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

        Modes:
        - mock (default): no external call, useful for local and staging tests
        - live: POST payout request to BANK_PAYOUT_API_URL
        """
        logger.info(f'Processing bank transfer for withdrawal {withdrawal.id}')

        transaction_id = f"BANK_{withdrawal.id}_{int(timezone.now().timestamp())}"
        payout_mode = self.bank_payout_mode or 'mock'

        # Safe default for local development and mock testing.
        if payout_mode != 'live':
            return {
                'success': True,
                'transaction_id': transaction_id,
                'gateway_response': {
                    'status': 'pending',
                    'message': 'Bank transfer initiated in mock mode.',
                    'transaction_id': transaction_id,
                    'gateway': 'bank_transfer',
                    'mode': 'mock',
                    'processed_at': timezone.now().isoformat()
                },
                'failure_reason': None
            }

        if not self.bank_payout_api_url:
            return {
                'success': False,
                'transaction_id': None,
                'gateway_response': {'status': 'error', 'message': 'BANK_PAYOUT_API_URL is not configured'},
                'failure_reason': 'Live bank payout mode requires BANK_PAYOUT_API_URL'
            }

        payload = self._build_bank_payout_payload(withdrawal, transaction_id)
        headers = {'Content-Type': 'application/json'}
        if self.bank_payout_api_key:
            headers['Authorization'] = f'Bearer {self.bank_payout_api_key}'

        try:
            response = requests.post(
                self.bank_payout_api_url,
                json=payload,
                headers=headers,
                timeout=self.bank_payout_timeout_seconds,
            )

            try:
                gateway_data = response.json()
            except Exception:
                gateway_data = {'raw_response': response.text}

            if 200 <= response.status_code < 300:
                gateway_status = str(gateway_data.get('status', '')).lower()
                remote_transaction_id = (
                    gateway_data.get('transaction_id')
                    or gateway_data.get('id')
                    or gateway_data.get('reference')
                    or transaction_id
                )
                is_success = gateway_status in ('success', 'queued', 'pending', '')
                if is_success:
                    return {
                        'success': True,
                        'transaction_id': str(remote_transaction_id),
                        'gateway_response': {
                            **gateway_data,
                            'gateway': 'bank_transfer',
                            'mode': 'live',
                            'http_status': response.status_code,
                        },
                        'failure_reason': None
                    }

            error_message = (
                gateway_data.get('message')
                if isinstance(gateway_data, dict)
                else None
            ) or f"Bank payout API returned HTTP {response.status_code}"
            return {
                'success': False,
                'transaction_id': None,
                'gateway_response': {
                    **(gateway_data if isinstance(gateway_data, dict) else {'response': gateway_data}),
                    'gateway': 'bank_transfer',
                    'mode': 'live',
                    'http_status': response.status_code,
                },
                'failure_reason': error_message
            }
        except requests.RequestException as e:
            logger.error(f'Bank payout API request failed for withdrawal {withdrawal.id}: {str(e)}', exc_info=True)
            return {
                'success': False,
                'transaction_id': None,
                'gateway_response': {'status': 'error', 'error': str(e), 'gateway': 'bank_transfer', 'mode': 'live'},
                'failure_reason': f'Bank payout API error: {str(e)}'
            }

    def _build_bank_payout_payload(self, withdrawal, reference: str) -> Dict[str, Any]:
        return {
            'reference': reference,
            'withdrawal_id': withdrawal.id,
            'user_id': withdrawal.user_id,
            'username': getattr(withdrawal.user, 'username', ''),
            'amount': str(withdrawal.amount),
            'currency': getattr(settings, 'LIPILA_CURRENCY', 'ZMW'),
            'account_details': withdrawal.account_details,
        }
    
    def _process_mobile_money(self, withdrawal) -> Dict[str, Any]:
        """Process mobile money withdrawal through the active provider."""
        active_provider = get_active_payment_provider()
        if active_provider == 'zynle':
            account_number = self._extract_phone_number(withdrawal.account_details)
            return get_payment_gateway('zynle').process_withdrawal(
                withdrawal,
                mobile_number=account_number,
            )

        return self._process_lipila_mobile_money(withdrawal)

    def _process_lipila_mobile_money(self, withdrawal) -> Dict[str, Any]:
        """Process mobile money withdrawal via Lipila disbursement API."""
        from services.payments.lipila_service import LipilaService, get_lipila_service

        if bool(getattr(settings, 'LIPILA_MOCK_MODE', False)):
            transaction_id = f"MOCK_MM_{withdrawal.id}_{int(timezone.now().timestamp())}"
            return {
                'success': True,
                'transaction_id': transaction_id,
                'gateway_response': {
                    'status': 'pending',
                    'message': 'Mock Lipila mobile money disbursement.',
                    'transaction_id': transaction_id,
                    'gateway': 'lipila',
                    'mode': 'mock',
                },
                'failure_reason': None,
            }

        secret = (
            getattr(settings, 'LIPILA_SECRET_KEY', '')
            or getattr(settings, 'LIPILA_API_KEY', '')
        ).strip()
        if not secret:
            return {
                'success': False,
                'transaction_id': None,
                'gateway_response': {'status': 'error', 'message': 'Lipila not configured'},
                'failure_reason': 'LIPILA_SECRET_KEY is not configured',
            }

        account_number = self._extract_phone_number(withdrawal.account_details)
        if not account_number:
            return {
                'success': False,
                'transaction_id': None,
                'gateway_response': {'status': 'error', 'message': 'Invalid mobile number'},
                'failure_reason': 'Account details must include a valid mobile money number (e.g. 26097xxxxxxx)',
            }

        reference_id = self._withdrawal_reference_id(withdrawal)
        try:
            client = get_lipila_service()
            callback_url = self._lipila_disbursement_callback_url()
            resp = client.disburse_mobile_money(
                reference_id=reference_id,
                amount=float(withdrawal.amount),
                account_number=account_number,
                currency=getattr(settings, 'LIPILA_CURRENCY', 'ZMW'),
                narration=f'Withdrawal for {withdrawal.user.username}',
                callback_url=callback_url,
                idempotency_key=f'withdrawal-{withdrawal.id}',
            )
            identifier = resp.get('identifier') or reference_id
            status = str(resp.get('status', 'Pending'))
            is_ok = status.lower() in ('pending', 'successful', 'success', '')
            if is_ok:
                return {
                    'success': True,
                    'transaction_id': str(identifier),
                    'gateway_response': {**resp, 'gateway': 'lipila', 'reference_id': reference_id},
                    'failure_reason': None,
                }
            return {
                'success': False,
                'transaction_id': None,
                'gateway_response': resp,
                'failure_reason': resp.get('message', 'Lipila disbursement failed'),
            }
        except requests.exceptions.Timeout as e:
            logger.error(f'Lipila disbursement timeout for withdrawal {withdrawal.id}: {str(e)}', exc_info=True)
            return {
                'success': False,
                'transaction_id': reference_id,
                'gateway_response': {
                    'status': 'unknown_timeout',
                    'error': str(e),
                    'gateway': 'lipila',
                    'reference_id': reference_id,
                    'referenceId': reference_id,
                },
                'failure_reason': 'Lipila request timed out after submission; awaiting callback or manual verification.',
            }
        except requests.exceptions.RequestException as e:
            response_details = LipilaService.response_log_details(getattr(e, 'response', None))
            logger.error(
                'Lipila disbursement error for withdrawal %s: %s response=%s',
                withdrawal.id,
                str(e),
                response_details,
                exc_info=True,
            )
            return {
                'success': False,
                'transaction_id': None,
                'gateway_response': {
                    'status': 'error',
                    'error': str(e),
                    'gateway': 'lipila',
                    'reference_id': reference_id,
                    'referenceId': reference_id,
                    'lipila_response': response_details,
                },
                'failure_reason': f'Lipila API error: {str(e)}',
            }

    @staticmethod
    def _extract_phone_number(account_details: str) -> Optional[str]:
        import re
        text = (account_details or '').strip()
        if not text:
            return None
        match = re.search(r'(\+?260\d{9}|0\d{9})', text.replace(' ', ''))
        if match:
            digits = re.sub(r'\D', '', match.group(1))
            if digits.startswith('0') and len(digits) == 10:
                return '260' + digits[1:]
            if digits.startswith('260') and len(digits) == 12:
                return digits
        digits_only = re.sub(r'\D', '', text)
        if digits_only.startswith('260') and len(digits_only) == 12:
            return digits_only
        return None

    @staticmethod
    def _withdrawal_reference_id(withdrawal) -> str:
        if isinstance(withdrawal.gateway_response, dict):
            for key in ('reference_id', 'referenceId'):
                value = str(withdrawal.gateway_response.get(key) or '').strip()
                if value:
                    return value
        if withdrawal.transaction_id and str(withdrawal.transaction_id).startswith('WDR_'):
            return str(withdrawal.transaction_id)
        return f'WDR_{withdrawal.id}'

    @staticmethod
    def _lipila_disbursement_callback_url() -> Optional[str]:
        configured = (
            getattr(settings, 'LIPILA_DISBURSEMENT_CALLBACK_URL', '')
            or getattr(settings, 'LIPILA_WEBHOOK_URL', '')
            or ''
        ).strip()
        if configured:
            return configured

        public_base = (getattr(settings, 'PUBLIC_BASE_URL', '') or '').strip()
        if not public_base:
            return None
        return urljoin(public_base.rstrip('/') + '/', reverse('api_lipila_webhook').lstrip('/'))

    def _initialize_lipila_via_gateway(
        self,
        deposit,
        callback_url: Optional[str],
        mobile_number: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Delegate Lipila deposit initiation to the payment gateway abstraction."""

        class _CallbackRequest:
            def build_absolute_uri(self, path):
                return callback_url or path

        result = get_payment_gateway().initiate_payment(
            deposit,
            _CallbackRequest(),
            mobile_number=mobile_number,
        )
        return {
            'success': result.success,
            'authorization_url': result.payment_url,
            'payment_reference': result.payment_reference,
            'gateway_response': result.raw_response,
            'failure_reason': result.failure_reason,
        }

    def _initialize_bank_transfer_deposit(self, deposit, callback_url: Optional[str]) -> Dict[str, Any]:
        """
        Initialize a bank transfer deposit (manual processing).
        """
        payment_reference = f'BANKDEP_{deposit.id}_{int(timezone.now().timestamp())}'
        return {
            'success': True,
            'authorization_url': None,
            'payment_reference': payment_reference,
            'gateway_response': {
                'status': 'pending',
                'reference': payment_reference,
                'gateway': 'bank_transfer'
            },
            'failure_reason': None
        }

    def _initialize_paypal_deposit(self, deposit, callback_url: Optional[str]) -> Dict[str, Any]:
        """
        Initialize a PayPal deposit (not yet implemented).
        """
        logger.warning(f'PayPal deposit processing not yet implemented for deposit {deposit.id}')
        return {
            'success': False,
            'authorization_url': None,
            'payment_reference': None,
            'gateway_response': {'status': 'error', 'message': 'PayPal integration not yet available'},
            'failure_reason': 'PayPal deposit processing is not yet implemented'
        }

    def _initialize_stripe_deposit(self, deposit, callback_url: Optional[str]) -> Dict[str, Any]:
        """
        Initialize a Stripe deposit (not yet implemented).
        """
        logger.warning(f'Stripe deposit processing not yet implemented for deposit {deposit.id}')
        return {
            'success': False,
            'authorization_url': None,
            'payment_reference': None,
            'gateway_response': {'status': 'error', 'message': 'Stripe integration not yet available'},
            'failure_reason': 'Stripe deposit processing is not yet implemented'
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
