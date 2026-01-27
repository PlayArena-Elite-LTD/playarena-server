"""
Utility functions for wallet operations, transaction reconciliation and auditing.
"""
from decimal import Decimal
from django.db import transaction
from django.db.models import Sum, Q
from django.utils import timezone
from datetime import timedelta
import logging

from .models import Wallet, Transaction, Deposit, Withdrawal

logger = logging.getLogger(__name__)


@transaction.atomic
def complete_deposit_and_credit_wallet(deposit):
    """
    Securely complete a deposit and credit the wallet balance
    
    Security features:
    - Atomic transaction (all or nothing)
    - Idempotent (won't credit twice if already completed)
    - Creates transaction record for audit
    - Prevents race conditions with select_for_update
    
    Args:
        deposit: Deposit instance to complete
    
    Returns:
        dict: {
            'success': bool,
            'wallet_credited': bool,
            'transaction_created': bool,
            'message': str
        }
    """
    try:
        # Security: Lock deposit to prevent concurrent processing
        deposit = Deposit.objects.select_for_update().get(id=deposit.id)
        
        # Security: Check if already completed (idempotency)
        if deposit.status == 'COMPLETED':
            # Check if wallet was already credited
            existing_transaction = Transaction.objects.filter(
                wallet=deposit.wallet,
                transaction_type='DEPOSIT',
                description__contains=f"Deposit of ${deposit.amount}",
                created_at__gte=deposit.created_at
            ).first()
            
            if existing_transaction:
                logger.info(
                    f"Deposit {deposit.id} already completed and wallet credited - "
                    f"Transaction: {existing_transaction.id}"
                )
                return {
                    'success': True,
                    'wallet_credited': True,
                    'transaction_created': False,
                    'message': 'Deposit already completed and wallet credited'
                }
            else:
                # Status is COMPLETED but no transaction found - credit now
                logger.warning(
                    f"Deposit {deposit.id} marked COMPLETED but wallet not credited - "
                    f"Crediting now"
                )
        
        # Security: Only process if status allows
        if deposit.status in ['FAILED', 'CANCELLED']:
            logger.warning(
                f"Cannot credit wallet for deposit {deposit.id} - "
                f"Status: {deposit.status}"
            )
            return {
                'success': False,
                'wallet_credited': False,
                'transaction_created': False,
                'message': f'Cannot credit wallet for deposit with status: {deposit.status}'
            }
        
        # Get wallet with lock
        wallet = Wallet.objects.select_for_update().get(id=deposit.wallet.id)
        
        # Update deposit status
        deposit.status = 'COMPLETED'
        if not deposit.completed_at:
            deposit.completed_at = timezone.now()
        if not deposit.verification_hash:
            # Generate verification hash if method exists (security feature)
            if hasattr(deposit, 'generate_verification_hash'):
                deposit.verification_hash = deposit.generate_verification_hash()
            else:
                # Fallback: generate simple hash if method doesn't exist
                import hashlib
                hash_data = f"{deposit.id}_{deposit.user_id}_{deposit.amount}_{deposit.status}_{deposit.transaction_id}"
                deposit.verification_hash = hashlib.sha256(hash_data.encode()).hexdigest()
        
        # Credit wallet balance
        wallet.balance += deposit.amount
        
        # Create transaction record for audit
        transaction_record = Transaction.objects.create(
            wallet=wallet,
            amount=deposit.amount,
            transaction_type='DEPOSIT',
            description=f"Deposit of ${deposit.amount:.2f} via {deposit.get_payment_method_display()}"
        )
        
        # Save both atomically
        deposit.save(update_fields=['status', 'completed_at', 'verification_hash'])
        wallet.save(update_fields=['balance'])
        
        logger.info(
            f"Deposit {deposit.id} completed and wallet credited - "
            f"User: {deposit.user.username}, Amount: ${deposit.amount}, "
            f"New Balance: ${wallet.balance}, Transaction: {transaction_record.id}"
        )
        
        return {
            'success': True,
            'wallet_credited': True,
            'transaction_created': True,
            'message': 'Deposit completed and wallet credited successfully',
            'new_balance': wallet.balance,
            'transaction_id': transaction_record.id
        }
        
    except Deposit.DoesNotExist:
        logger.error(f"Deposit {deposit.id} not found")
        return {
            'success': False,
            'wallet_credited': False,
            'transaction_created': False,
            'message': 'Deposit not found'
        }
    except Exception as e:
        logger.error(
            f"Error completing deposit {deposit.id} and crediting wallet - "
            f"Error: {str(e)}",
            exc_info=True
        )
        # Transaction will rollback automatically
        return {
            'success': False,
            'wallet_credited': False,
            'transaction_created': False,
            'message': f'Error: {str(e)}'
        }


@transaction.atomic
def process_withdrawal_and_debit_wallet(withdrawal):
    """
    Securely process a withdrawal and debit the wallet balance
    
    Security features:
    - Atomic transaction (all or nothing)
    - Idempotent (won't debit twice if already completed)
    - Creates transaction record for audit
    - Prevents race conditions with select_for_update
    - Validates wallet balance before debiting
    
    Args:
        withdrawal: Withdrawal instance to process
    
    Returns:
        dict: {
            'success': bool,
            'wallet_debited': bool,
            'transaction_created': bool,
            'new_balance': Decimal,
            'message': str
        }
    """
    try:
        # Security: Lock withdrawal to prevent concurrent processing
        withdrawal = Withdrawal.objects.select_for_update().get(id=withdrawal.id)
        
        # Security: Check if already completed (idempotency)
        if withdrawal.status == 'COMPLETED':
            # Check if wallet was already debited
            existing_transaction = Transaction.objects.filter(
                wallet=withdrawal.wallet,
                transaction_type='WITHDRAWAL',
                description__contains=f"Withdrawal of ${withdrawal.amount}",
                created_at__gte=withdrawal.created_at
            ).first()
            
            if existing_transaction:
                logger.info(
                    f"Withdrawal {withdrawal.id} already completed and wallet debited - "
                    f"Transaction: {existing_transaction.id}"
                )
                return {
                    'success': True,
                    'wallet_debited': True,
                    'transaction_created': False,
                    'new_balance': withdrawal.wallet.balance,
                    'message': 'Withdrawal already completed and wallet debited'
                }
            else:
                # Status is COMPLETED but no transaction found - debit now
                logger.warning(
                    f"Withdrawal {withdrawal.id} marked COMPLETED but wallet not debited - "
                    f"Debiting now"
                )
        
        # Security: Only process if status allows
        if withdrawal.status in ['FAILED', 'CANCELLED']:
            logger.warning(
                f"Cannot debit wallet for withdrawal {withdrawal.id} - "
                f"Status: {withdrawal.status}"
            )
            return {
                'success': False,
                'wallet_debited': False,
                'transaction_created': False,
                'new_balance': withdrawal.wallet.balance,
                'message': f'Cannot debit wallet for withdrawal with status: {withdrawal.status}'
            }
        
        # Get wallet with lock
        wallet = Wallet.objects.select_for_update().get(id=withdrawal.wallet.id)
        
        # Security: Validate balance before debiting (double-check)
        if withdrawal.amount > wallet.balance:
            logger.error(
                f"Insufficient balance for withdrawal {withdrawal.id} - "
                f"Required: ${withdrawal.amount}, Available: ${wallet.balance}"
            )
            return {
                'success': False,
                'wallet_debited': False,
                'transaction_created': False,
                'new_balance': wallet.balance,
                'message': f'Insufficient balance. Required: ${withdrawal.amount}, Available: ${wallet.balance}'
            }
        
        # Update withdrawal status
        withdrawal.status = 'COMPLETED'
        
        # Debit wallet balance
        wallet.balance -= withdrawal.amount
        
        # Create transaction record for audit (negative amount for withdrawal)
        transaction_record = Transaction.objects.create(
            wallet=wallet,
            amount=-withdrawal.amount,  # Negative for withdrawal
            transaction_type='WITHDRAWAL',
            description=f"Withdrawal of ${withdrawal.amount:.2f} via {withdrawal.get_payment_method_display()}"
        )
        
        # Save both atomically
        withdrawal.save(update_fields=['status'])
        wallet.save(update_fields=['balance'])
        
        logger.info(
            f"Withdrawal {withdrawal.id} completed and wallet debited - "
            f"User: {withdrawal.user.username}, Amount: ${withdrawal.amount}, "
            f"New Balance: ${wallet.balance}, Transaction: {transaction_record.id}"
        )
        
        return {
            'success': True,
            'wallet_debited': True,
            'transaction_created': True,
            'message': 'Withdrawal completed and wallet debited successfully',
            'new_balance': wallet.balance,
            'transaction_id': transaction_record.id
        }
        
    except Withdrawal.DoesNotExist:
        logger.error(f"Withdrawal {withdrawal.id} not found")
        return {
            'success': False,
            'wallet_debited': False,
            'transaction_created': False,
            'new_balance': None,
            'message': 'Withdrawal not found'
        }
    except Exception as e:
        logger.error(
            f"Error processing withdrawal {withdrawal.id} and debiting wallet - "
            f"Error: {str(e)}",
            exc_info=True
        )
        # Transaction will rollback automatically
        return {
            'success': False,
            'wallet_debited': False,
            'transaction_created': False,
            'new_balance': None,
            'message': f'Error: {str(e)}'
        }