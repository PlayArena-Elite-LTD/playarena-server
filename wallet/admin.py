from django.contrib import admin
from django.db import transaction
from django.utils import timezone
from .models import Wallet, Transaction, Deposit, Withdrawal, SavedPaymentMethod

@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ['user', 'balance', 'id']
    search_fields = ['user__username', 'user__email']
    readonly_fields = ['balance']

@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ['wallet', 'amount', 'transaction_type', 'description', 'created_at']
    list_filter = ['transaction_type', 'created_at']
    search_fields = ['wallet__user__username', 'description']
    readonly_fields = ['created_at']
    date_hierarchy = 'created_at'

@admin.register(Deposit)
class DepositAdmin(admin.ModelAdmin):
    list_display = ['user', 'amount', 'payment_method', 'status', 'created_at']
    list_filter = ['status', 'payment_method', 'created_at']
    search_fields = ['user__username', 'user__email', 'transaction_id']
    readonly_fields = ['created_at', 'updated_at']
    date_hierarchy = 'created_at'
    actions = ['mark_as_completed', 'mark_as_failed', 'mark_as_cancelled']
    
    fieldsets = (
        ('User Information', {
            'fields': ('user', 'wallet')
        }),
        ('Deposit Details', {
            'fields': ('amount', 'payment_method', 'status', 'transaction_id')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    @admin.action(description='Mark selected deposits as COMPLETED')
    @transaction.atomic
    def mark_as_completed(self, request, queryset):
        """Mark deposits as COMPLETED and update wallet balance"""
        count = 0
        for deposit in queryset:
            if deposit.status == 'COMPLETED':
                continue  # Already completed
            if deposit.status in ['FAILED', 'CANCELLED']:
                continue  # Cannot change from final states
            
            # Update wallet balance
            wallet = deposit.wallet
            wallet.balance += deposit.amount
            wallet.save()
            
            # Create transaction record
            Transaction.objects.create(
                wallet=wallet,
                amount=deposit.amount,
                transaction_type='DEPOSIT',
                description=f"Deposit of ${deposit.amount} via {deposit.get_payment_method_display()}"
            )
            
            # Update deposit status (use update() to bypass clean() validation)
            Deposit.objects.filter(id=deposit.id).update(status='COMPLETED', updated_at=timezone.now())
            count += 1
        
        self.message_user(request, f'{count} deposit(s) marked as completed.')
    
    @admin.action(description='Mark selected deposits as FAILED')
    def mark_as_failed(self, request, queryset):
        """Mark deposits as FAILED"""
        count = Deposit.objects.filter(
            id__in=queryset.values_list('id', flat=True),
            status__in=['PENDING', 'PROCESSING']
        ).update(status='FAILED', updated_at=timezone.now())
        self.message_user(request, f'{count} deposit(s) marked as failed.')
    
    @admin.action(description='Mark selected deposits as CANCELLED')
    def mark_as_cancelled(self, request, queryset):
        """Mark deposits as CANCELLED"""
        count = Deposit.objects.filter(
            id__in=queryset.values_list('id', flat=True),
            status__in=['PENDING', 'PROCESSING']
        ).update(status='CANCELLED', updated_at=timezone.now())
        self.message_user(request, f'{count} deposit(s) marked as cancelled.')

@admin.register(Withdrawal)
class WithdrawalAdmin(admin.ModelAdmin):
    list_display = ['user', 'amount', 'payment_method', 'status', 'created_at']
    list_filter = ['status', 'payment_method', 'created_at']
    search_fields = ['user__username', 'user__email', 'transaction_id', 'account_details']
    readonly_fields = ['created_at', 'updated_at']
    date_hierarchy = 'created_at'
    actions = ['mark_as_completed', 'mark_as_failed', 'mark_as_cancelled', 'process_withdrawals']
    
    fieldsets = (
        ('User Information', {
            'fields': ('user', 'wallet')
        }),
        ('Withdrawal Details', {
            'fields': ('amount', 'payment_method', 'account_details', 'status', 'transaction_id')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    @admin.action(description='Mark selected withdrawals as COMPLETED')
    @transaction.atomic
    def mark_as_completed(self, request, queryset):
        """Mark withdrawals as COMPLETED and update wallet balance"""
        count = 0
        for withdrawal in queryset:
            if withdrawal.status == 'COMPLETED':
                continue  # Already completed
            if withdrawal.status in ['FAILED', 'CANCELLED']:
                continue  # Cannot change from final states
            
            # Update wallet balance (subtract amount)
            wallet = withdrawal.wallet
            wallet.balance -= withdrawal.amount
            wallet.save()
            
            # Create transaction record (negative amount for withdrawal)
            Transaction.objects.create(
                wallet=wallet,
                amount=-withdrawal.amount,
                transaction_type='WITHDRAWAL',
                description=f"Withdrawal of ${withdrawal.amount} via {withdrawal.get_payment_method_display()}"
            )
            
            # Update withdrawal status (use update() to bypass clean() validation)
            Withdrawal.objects.filter(id=withdrawal.id).update(status='COMPLETED', updated_at=timezone.now())
            count += 1
        
        self.message_user(request, f'{count} withdrawal(s) marked as completed.')
    
    @admin.action(description='Mark selected withdrawals as FAILED')
    def mark_as_failed(self, request, queryset):
        """Mark withdrawals as FAILED"""
        count = Withdrawal.objects.filter(
            id__in=queryset.values_list('id', flat=True),
            status__in=['PENDING', 'PROCESSING']
        ).update(status='FAILED', updated_at=timezone.now())
        self.message_user(request, f'{count} withdrawal(s) marked as failed.')
    
    @admin.action(description='Mark selected withdrawals as CANCELLED')
    def mark_as_cancelled(self, request, queryset):
        """Mark withdrawals as CANCELLED"""
        count = Withdrawal.objects.filter(
            id__in=queryset.values_list('id', flat=True),
            status__in=['PENDING', 'PROCESSING']
        ).update(status='CANCELLED', updated_at=timezone.now())
        self.message_user(request, f'{count} withdrawal(s) marked as cancelled.')
    
    @admin.action(description='Process selected withdrawals manually')
    @transaction.atomic
    def process_withdrawals(self, request, queryset):
        """
        Manually process selected withdrawals through payment gateway.
        This action uses the same processing logic as the management command.
        """
        from wallet.payment_manager import get_payment_manager
        from wallet.notifications import (
            notify_withdrawal_processing,
            notify_withdrawal_completed,
            notify_withdrawal_failed,
            notify_withdrawal_retry
        )
        import logging
        
        logger = logging.getLogger(__name__)
        
        processed_count = 0
        completed_count = 0
        failed_count = 0
        skipped_count = 0
        
        for withdrawal in queryset:
            # Skip if already in final state
            if withdrawal.is_final:
                skipped_count += 1
                continue
            
            # Skip if not in processable state
            if withdrawal.status not in ['PENDING', 'PROCESSING']:
                skipped_count += 1
                continue
            
            try:
                processed_count += 1
                
                # Update status to PROCESSING if PENDING
                if withdrawal.status == 'PENDING':
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
                    # Withdrawal successful
                    wallet = withdrawal.wallet
                    
                    # Update wallet balance (subtract amount)
                    wallet.balance -= withdrawal.amount
                    wallet.save()
                    
                    # Create transaction record
                    Transaction.objects.create(
                        wallet=wallet,
                        amount=-withdrawal.amount,
                        transaction_type='WITHDRAWAL',
                        description=f"Withdrawal of ${withdrawal.amount} via {withdrawal.get_payment_method_display()}"
                    )
                    
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
                        f'Withdrawal {withdrawal.id} processed successfully via admin. '
                        f'Transaction ID: {result["transaction_id"]}'
                    )
                else:
                    # Withdrawal failed
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
                        
                        failed_count += 1
                        
                        # Send failure notification
                        withdrawal.refresh_from_db()
                        notify_withdrawal_failed(withdrawal, result['failure_reason'])
                        
                        logger.warning(
                            f'Withdrawal {withdrawal.id} failed after {new_retry_count} retries. '
                            f'Reason: {result["failure_reason"]}'
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
                        
                        failed_count += 1  # Count as failed for this attempt
                        
                        # Send retry notification
                        withdrawal.refresh_from_db()
                        notify_withdrawal_retry(withdrawal, new_retry_count, withdrawal.max_retry_count)
                        
                        logger.info(
                            f'Withdrawal {withdrawal.id} failed, will retry. '
                            f'Retry count: {new_retry_count}/{withdrawal.max_retry_count}. '
                            f'Reason: {result["failure_reason"]}'
                        )
            
            except Exception as e:
                logger.error(
                    f'Error processing withdrawal {withdrawal.id} via admin: {str(e)}',
                    exc_info=True
                )
                
                # Mark as FAILED if error occurred
                try:
                    Withdrawal.objects.filter(id=withdrawal.id).update(
                        status='FAILED',
                        failure_reason=f'Processing error: {str(e)}',
                        updated_at=timezone.now()
                    )
                    failed_count += 1
                    
                    # Send failure notification
                    withdrawal.refresh_from_db()
                    notify_withdrawal_failed(withdrawal, f'Processing error: {str(e)}')
                except Exception as update_error:
                    logger.error(
                        f'Error updating withdrawal {withdrawal.id} status: {str(update_error)}',
                        exc_info=True
                    )
        
        # Report results
        message_parts = []
        if processed_count > 0:
            message_parts.append(f'{processed_count} processed')
        if completed_count > 0:
            message_parts.append(f'{completed_count} completed')
        if failed_count > 0:
            message_parts.append(f'{failed_count} failed')
        if skipped_count > 0:
            message_parts.append(f'{skipped_count} skipped')
        
        message = f"Withdrawal processing: {', '.join(message_parts)}."
        self.message_user(request, message)


@admin.register(SavedPaymentMethod)
class SavedPaymentMethodAdmin(admin.ModelAdmin):
    list_display = ['user', 'label', 'payment_method_type', 'is_default', 'is_active', 'created_at']
    list_filter = ['payment_method_type', 'is_default', 'is_active', 'created_at']
    search_fields = ['user__username', 'user__email', 'label', 'account_details']
    readonly_fields = ['created_at', 'updated_at', 'masked_account_display']
    date_hierarchy = 'created_at'
    
    fieldsets = (
        ('User Information', {
            'fields': ('user',)
        }),
        ('Payment Method Details', {
            'fields': ('payment_method_type', 'label', 'account_details', 'masked_account_display', 'gateway_identifier', 'metadata')
        }),
        ('Settings', {
            'fields': ('is_default', 'is_active')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def masked_account_display(self, obj):
        """Display masked account details in admin"""
        if obj:
            return obj.mask_account_details()
        return "N/A"
    masked_account_display.short_description = 'Masked Account Details'
    
    def get_queryset(self, request):
        """Security: Filter queryset based on user permissions"""
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        # Non-superusers can only see their own payment methods
        return qs.filter(user=request.user)