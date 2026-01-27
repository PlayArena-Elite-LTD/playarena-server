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


    def process_withdrawal(self, withdrawal):
        """
        Process withdrawal through payment gateway (Paystack or Flutterwave)
        
        Security: Uses select_for_update() to prevent concurrent processing
        
        This method handles the complete withdrawal flow:
        1. Lock withdrawal to prevent concurrent processing
        2. Parse account details from withdrawal
        3. Create transfer recipient/beneficiary
        4. Initiate transfer to recipient
        5. Update withdrawal with gateway transaction IDs
        
        Args:
            withdrawal: Withdrawal model instance
        
        Returns:
            dict: {
                'success': bool,
                'transaction_id': str,
                'recipient_code': str (Paystack) or beneficiary_id (Flutterwave),
                'transfer_code': str,
                'reference': str,
                'status': str,
                'message': str,
                'gateway': str,
                'gateway_response': dict,
                'failure_reason': str (if failed)
            }
        """
        from django.db import transaction
        
        # Security: Lock withdrawal to prevent concurrent processing
        with transaction.atomic():
            withdrawal = withdrawal.__class__.objects.select_for_update().get(id=withdrawal.id)
            
            payment_method = withdrawal.payment_method
            amount = withdrawal.amount
            user = withdrawal.user
            
            try:
                if payment_method == 'FLUTTERWAVE':
                    return self._process_flutterwave_withdrawal(withdrawal, amount, user)
                elif payment_method == 'PAYSTACK':
                    return self._process_paystack_withdrawal(withdrawal, amount, user)
                else:
                    # For other payment methods, return manual processing
                    return {
                        'success': False,
                        'transaction_id': None,
                        'recipient_code': None,
                        'transfer_code': None,
                        'reference': None,
                        'status': None,
                        'message': 'Manual processing required for this payment method',
                        'gateway': payment_method,
                        'gateway_response': {},
                        'failure_reason': 'Manual processing required'
                    }
            except Exception as e:
                logger.error(f"Error processing withdrawal {withdrawal.id}: {str(e)}")
                return {
                    'success': False,
                    'transaction_id': None,
                    'recipient_code': None,
                    'transfer_code': None,
                    'reference': None,
                    'status': None,
                    'message': f'Withdrawal processing failed: {str(e)}',
                    'gateway': payment_method,
                    'gateway_response': {},
                    'failure_reason': str(e)
                }
    
    def _parse_account_details(self, account_details):
        """
        Parse account details from text field
        
        Expected formats:
        - "Account Number: 1234567890, Bank Code: 058, Account Name: John Doe"
        - "Account: 1234567890, Bank: 058, Name: John Doe"
        - Simple: "1234567890" (minimal parsing)
        
        Returns:
            dict: {
                'account_number': str,
                'bank_code': str,
                'account_name': str,
                'email': str (optional)
            }
        """
        import re
        
        details = {
            'account_number': None,
            'bank_code': None,
            'account_name': None,
            'email': None
        }
        
        # Try to extract account number
        account_patterns = [
            r'account\s*(?:number|no|#)?\s*:?\s*(\d+)',
            r'acc\s*(?:number|no|#)?\s*:?\s*(\d+)',
            r'^(\d{10,})$',  # Just numbers (10+ digits)
        ]
        for pattern in account_patterns:
            match = re.search(pattern, account_details, re.IGNORECASE)
            if match:
                details['account_number'] = match.group(1)
                break
        
        # Try to extract bank code
        bank_patterns = [
            r'bank\s*(?:code|id)?\s*:?\s*(\d+)',
            r'bank\s*:?\s*(\d+)',
        ]
        for pattern in bank_patterns:
            match = re.search(pattern, account_details, re.IGNORECASE)
            if match:
                details['bank_code'] = match.group(1)
                break
        
        # Try to extract account name
        name_patterns = [
            r'(?:account\s*)?name\s*:?\s*([A-Za-z\s]+)',
            r'name\s*:?\s*([A-Za-z\s]+)',
        ]
        for pattern in name_patterns:
            match = re.search(pattern, account_details, re.IGNORECASE)
            if match:
                details['account_name'] = match.group(1).strip()
                break
        
        # Try to extract email
        email_pattern = r'[\w\.-]+@[\w\.-]+\.\w+'
        email_match = re.search(email_pattern, account_details)
        if email_match:
            details['email'] = email_match.group(0)
        
        return details
    
    def _process_paystack_withdrawal(self, withdrawal, amount, user):
        """Process Paystack withdrawal"""
        try:
            # Parse account details
            account_info = self._parse_account_details(withdrawal.account_details)
            
            if not account_info.get('account_number'):
                return {
                    'success': False,
                    'recipient_code': None,
                    'transfer_code': None,
                    'reference': None,
                    'status': None,
                    'message': 'Could not parse account number from account details',
                    'gateway': 'PAYSTACK'
                }
            
            # Create transfer recipient
            recipient_result = self.paystack_service.create_transfer_recipient(
                account_number=account_info['account_number'],
                bank_code=account_info.get('bank_code') or '058',  # Default bank code if not provided
                account_name=account_info.get('account_name') or user.get_full_name() or user.username,
                email=account_info.get('email') or user.email,
                currency=getattr(settings, 'DEFAULT_PAYMENT_CURRENCY', 'NGN')
            )
            
            if not recipient_result['success']:
                return {
                    'success': False,
                    'recipient_code': None,
                    'transfer_code': None,
                    'reference': None,
                    'status': None,
                    'message': f"Failed to create recipient: {recipient_result.get('message')}",
                    'gateway': 'PAYSTACK'
                }
            
            recipient_code = recipient_result['recipient_code']
            
            # Create transfer reference
            transfer_reference = f"withdrawal_{withdrawal.id}_{withdrawal.created_at.timestamp()}"
            
            # Initiate transfer
            transfer_result = self.paystack_service.initiate_transfer(
                amount=amount,
                recipient_code=recipient_code,
                reason=f"Withdrawal for {user.username}",
                reference=transfer_reference,
                currency=getattr(settings, 'DEFAULT_PAYMENT_CURRENCY', 'NGN')
            )
            
            if not transfer_result['success']:
                return {
                    'success': False,
                    'recipient_code': recipient_code,
                    'transfer_code': None,
                    'reference': None,
                    'status': None,
                    'message': f"Failed to initiate transfer: {transfer_result.get('message')}",
                    'gateway': 'PAYSTACK'
                }
            
            # Update withdrawal with transaction IDs
            withdrawal.transaction_id = transfer_result.get('transfer_code') or transfer_result.get('reference')
            withdrawal.status = 'PROCESSING'
            withdrawal.save(update_fields=['transaction_id', 'status'])
            
            logger.info(
                f"Paystack withdrawal {withdrawal.id} processed - "
                f"User: {user.username}, Amount: ${amount}, "
                f"Recipient: {recipient_code}, Transfer: {transfer_result.get('transfer_code')}"
            )
            
            return {
                'success': True,
                'recipient_code': recipient_code,
                'transfer_code': transfer_result.get('transfer_code'),
                'reference': transfer_result.get('reference'),
                'status': transfer_result.get('status', 'pending'),
                'message': 'Withdrawal processed successfully',
                'gateway': 'PAYSTACK'
            }
            
        except Exception as e:
            logger.error(f"Exception processing Paystack withdrawal {withdrawal.id}: {str(e)}")
            return {
                'success': False,
                'recipient_code': None,
                'transfer_code': None,
                'reference': None,
                'status': None,
                'message': f'Error: {str(e)}',
                'gateway': 'PAYSTACK'
            }
    
    def _process_flutterwave_withdrawal(self, withdrawal, amount, user):
        """Process Flutterwave withdrawal"""
        try:
            # Parse account details
            account_info = self._parse_account_details(withdrawal.account_details)
            
            if not account_info.get('account_number'):
                return {
                    'success': False,
                    'beneficiary_id': None,
                    'transfer_id': None,
                    'reference': None,
                    'status': None,
                    'message': 'Could not parse account number from account details',
                    'gateway': 'FLUTTERWAVE'
                }
            
            if not account_info.get('account_name'):
                account_info['account_name'] = user.get_full_name() or user.username
            
            # Create transfer beneficiary
            beneficiary_result = self.flutterwave_service.create_transfer_beneficiary(
                account_number=account_info['account_number'],
                bank_code=account_info.get('bank_code') or '044',  # Default bank code if not provided
                account_name=account_info['account_name'],
                email=account_info.get('email') or user.email,
                currency=getattr(settings, 'DEFAULT_PAYMENT_CURRENCY', 'NGN')
            )
            
            if not beneficiary_result['success']:
                return {
                    'success': False,
                    'beneficiary_id': None,
                    'transfer_id': None,
                    'reference': None,
                    'status': None,
                    'message': f"Failed to create beneficiary: {beneficiary_result.get('message')}",
                    'gateway': 'FLUTTERWAVE'
                }
            
            beneficiary_id = beneficiary_result['beneficiary_id']
            
            # Create transfer reference
            transfer_reference = f"withdrawal_{withdrawal.id}_{withdrawal.created_at.timestamp()}"
            
            # Initiate transfer
            transfer_result = self.flutterwave_service.initiate_transfer(
                amount=amount,
                beneficiary_id=beneficiary_id,
                narration=f"Withdrawal for {user.username}",
                reference=transfer_reference,
                currency=getattr(settings, 'DEFAULT_PAYMENT_CURRENCY', 'NGN')
            )
            
            if not transfer_result['success']:
                return {
                    'success': False,
                    'beneficiary_id': beneficiary_id,
                    'transfer_id': None,
                    'reference': None,
                    'status': None,
                    'message': f"Failed to initiate transfer: {transfer_result.get('message')}",
                    'gateway': 'FLUTTERWAVE'
                }
            
            # Update withdrawal with transaction IDs
            withdrawal.transaction_id = str(transfer_result.get('transfer_id')) or transfer_result.get('reference')
            withdrawal.status = 'PROCESSING'
            withdrawal.save(update_fields=['transaction_id', 'status'])
            
            logger.info(
                f"Flutterwave withdrawal {withdrawal.id} processed - "
                f"User: {user.username}, Amount: ${amount}, "
                f"Beneficiary: {beneficiary_id}, Transfer: {transfer_result.get('transfer_id')}"
            )
            
            return {
                'success': True,
                'beneficiary_id': beneficiary_id,
                'transfer_id': transfer_result.get('transfer_id'),
                'reference': transfer_result.get('reference'),
                'status': transfer_result.get('status', 'pending'),
                'message': 'Withdrawal processed successfully',
                'gateway': 'FLUTTERWAVE'
            }
            
        except Exception as e:
            logger.error(f"Exception processing Flutterwave withdrawal {withdrawal.id}: {str(e)}")
            return {
                'success': False,
                'beneficiary_id': None,
                'transfer_id': None,
                'reference': None,
                'status': None,
                'message': f'Error: {str(e)}',
                'gateway': 'FLUTTERWAVE'
            }


# Backward compatibility alias
PaymentService = PaymentManager
