"""
Django management command to automatically process pending withdrawals.

This command:
- Queries PENDING withdrawals
- Processes each withdrawal through payment gateway
- Updates status based on result
- Handles retry logic
- Logs all operations
- Uses atomic transactions for data integrity

Security features:
- Rate limiting (processes limited withdrawals per run)
- Validation before processing
- Atomic operations
- Error handling and logging
"""

import logging
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from django.conf import settings

from wallet.models import Withdrawal
from wallet.payment_manager import get_payment_manager
from wallet.utils import refund_withdrawal_reservation
from wallet.notifications import (
    notify_withdrawal_processing,
    notify_withdrawal_completed,
    notify_withdrawal_failed,
    notify_withdrawal_retry
)

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Process pending withdrawals automatically'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--limit',
            type=int,
            default=50,
            help='Maximum number of withdrawals to process per run (default: 50)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Simulate processing without making changes'
        )
        parser.add_argument(
            '--force-retry',
            action='store_true',
            help='Process withdrawals that have exceeded max retry count'
        )
    
    def handle(self, *args, **options):
        limit = options['limit']
        dry_run = options['dry_run']
        force_retry = options['force_retry']
        
        # Security: Check if automatic processing is enabled
        auto_process_enabled = getattr(settings, 'WALLET_AUTO_PROCESS_WITHDRAWALS', True)
        
        if not auto_process_enabled:
            self.stdout.write(
                self.style.WARNING('Automatic withdrawal processing is disabled in settings.')
            )
            return
        
        # Query PENDING withdrawals
        # Security: Only process withdrawals that haven't exceeded retry limit (unless force-retry)
        if force_retry:
            withdrawals = Withdrawal.objects.filter(
                status='PENDING'
            ).order_by('created_at')[:limit]
        else:
            withdrawals = Withdrawal.objects.filter(
                status='PENDING'
            ).exclude(
                retry_count__gte=F('max_retry_count')
            ).order_by('created_at')[:limit]
        
        total_count = withdrawals.count()
        
        if total_count == 0:
            self.stdout.write(self.style.SUCCESS('No pending withdrawals to process.'))
            return
        
        self.stdout.write(f'Found {total_count} pending withdrawal(s) to process.')
        
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN MODE - No changes will be made.'))
        
        # Statistics
        processed_count = 0
        completed_count = 0
        failed_count = 0
        retry_count = 0
        error_count = 0
        
        # Process each withdrawal
        for withdrawal in withdrawals:
            try:
                # Security: Lock withdrawal to prevent concurrent processing
                withdrawal = Withdrawal.objects.select_for_update().get(id=withdrawal.id)
                
                # Skip if already in final state (race condition protection)
                if withdrawal.is_final:
                    self.stdout.write(
                        self.style.WARNING(
                            f'Skipping withdrawal {withdrawal.id} - already in final state: {withdrawal.status}'
                        )
                    )
                    continue
                
                # Skip if retry limit exceeded (unless force-retry)
                if not force_retry and withdrawal.retry_count >= withdrawal.max_retry_count:
                    self.stdout.write(
                        self.style.WARNING(
                            f'Skipping withdrawal {withdrawal.id} - retry limit exceeded ({withdrawal.retry_count}/{withdrawal.max_retry_count})'
                        )
                    )
                    continue
                
                processed_count += 1
                
                if dry_run:
                    self.stdout.write(
                        f'[DRY RUN] Would process withdrawal {withdrawal.id}: '
                        f'${withdrawal.amount} for {withdrawal.user.username}'
                    )
                    continue
                
                # Process withdrawal atomically
                with transaction.atomic():
                    # Update status to PROCESSING
                    Withdrawal.objects.filter(id=withdrawal.id).update(
                        status='PROCESSING',
                        updated_at=timezone.now()
                    )
                    withdrawal.refresh_from_db()
                    
                    # Send processing notification
                    notify_withdrawal_processing(withdrawal)
                    
                    # Process through payment gateway using PaymentManager
                    payment_manager = get_payment_manager()
                    result = payment_manager.process_withdrawal(withdrawal)
                    
                    if result['success']:
                        # Withdrawal successful; amount was reserved when request was created.
                        wallet = withdrawal.wallet
                        
                        # Update withdrawal status to COMPLETED
                        Withdrawal.objects.filter(id=withdrawal.id).update(
                            status='COMPLETED',
                            transaction_id=result['transaction_id'],
                            gateway_transaction_id=result['transaction_id'],
                            gateway_response=result['gateway_response'],
                            failure_reason=None,
                            updated_at=timezone.now()
                        )
                        
                        completed_count += 1
                        
                        # Send completion notification
                        withdrawal.refresh_from_db()
                        notify_withdrawal_completed(withdrawal)
                        
                        logger.info(
                            f'Withdrawal {withdrawal.id} completed successfully. '
                            f'Transaction ID: {result["transaction_id"]}'
                        )
                        self.stdout.write(
                            self.style.SUCCESS(
                                f'✓ Completed withdrawal {withdrawal.id}: '
                                f'${withdrawal.amount} for {withdrawal.user.username}'
                            )
                        )
                    else:
                        # Withdrawal failed
                        # Increment retry count
                        new_retry_count = withdrawal.retry_count + 1
                        
                        # Determine if we should retry or mark as failed
                        if new_retry_count >= withdrawal.max_retry_count:
                            # Max retries exceeded - mark as FAILED
                            Withdrawal.objects.filter(id=withdrawal.id).update(
                                status='FAILED',
                                gateway_response=result['gateway_response'],
                                failure_reason=result['failure_reason'],
                                retry_count=new_retry_count,
                                updated_at=timezone.now()
                            )
                            refund_withdrawal_reservation(withdrawal, result['failure_reason'])
                            
                            failed_count += 1
                            
                            # Send failure notification
                            withdrawal.refresh_from_db()
                            notify_withdrawal_failed(withdrawal, result['failure_reason'])
                            
                            logger.warning(
                                f'Withdrawal {withdrawal.id} failed after {new_retry_count} retries. '
                                f'Reason: {result["failure_reason"]}'
                            )
                            self.stdout.write(
                                self.style.ERROR(
                                    f'✗ Failed withdrawal {withdrawal.id} (max retries): '
                                    f'${withdrawal.amount} - {result["failure_reason"]}'
                                )
                            )
                        else:
                            # Retry later - set back to PENDING
                            Withdrawal.objects.filter(id=withdrawal.id).update(
                                status='PENDING',
                                gateway_response=result['gateway_response'],
                                failure_reason=result['failure_reason'],
                                retry_count=new_retry_count,
                                updated_at=timezone.now()
                            )
                            
                            retry_count += 1
                            
                            # Send retry notification
                            withdrawal.refresh_from_db()
                            notify_withdrawal_retry(withdrawal, new_retry_count, withdrawal.max_retry_count)
                            
                            logger.info(
                                f'Withdrawal {withdrawal.id} failed, will retry. '
                                f'Retry count: {new_retry_count}/{withdrawal.max_retry_count}. '
                                f'Reason: {result["failure_reason"]}'
                            )
                            self.stdout.write(
                                self.style.WARNING(
                                    f'↻ Retry withdrawal {withdrawal.id}: '
                                    f'${withdrawal.amount} (attempt {new_retry_count}/{withdrawal.max_retry_count})'
                                )
                            )
            
            except Exception as e:
                error_count += 1
                logger.error(
                    f'Error processing withdrawal {withdrawal.id}: {str(e)}',
                    exc_info=True
                )
                self.stdout.write(
                    self.style.ERROR(
                        f'✗ Error processing withdrawal {withdrawal.id}: {str(e)}'
                    )
                )
                
                # Mark as FAILED if error occurred
                if not dry_run:
                    try:
                        Withdrawal.objects.filter(id=withdrawal.id).update(
                            status='FAILED',
                            failure_reason=f'Processing error: {str(e)}',
                            updated_at=timezone.now()
                        )
                        refund_withdrawal_reservation(withdrawal, f'Processing error: {str(e)}')
                        
                        # Send failure notification
                        withdrawal.refresh_from_db()
                        notify_withdrawal_failed(withdrawal, f'Processing error: {str(e)}')
                    except Exception as update_error:
                        logger.error(
                            f'Error updating withdrawal {withdrawal.id} status: {str(update_error)}',
                            exc_info=True
                        )
        
        # Print summary
        self.stdout.write('\n' + '='*60)
        self.stdout.write(self.style.SUCCESS('Processing Summary:'))
        self.stdout.write(f'  Total found: {total_count}')
        self.stdout.write(f'  Processed: {processed_count}')
        self.stdout.write(f'  Completed: {completed_count}')
        self.stdout.write(f'  Failed: {failed_count}')
        self.stdout.write(f'  Retry scheduled: {retry_count}')
        self.stdout.write(f'  Errors: {error_count}')
        self.stdout.write('='*60)
