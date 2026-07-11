from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.contrib import messages
from django.utils import timezone
from django.utils.html import format_html
from django.http import HttpResponseRedirect
from django.urls import path, reverse
from .models import PaymentGatewaySetting, Wallet, Transaction, Deposit, Withdrawal, SavedPaymentMethod
from .utils import refund_withdrawal_reservation, process_withdrawal_and_debit_wallet


@admin.register(PaymentGatewaySetting)
class PaymentGatewaySettingAdmin(admin.ModelAdmin):
    fields = ('active_provider', 'updated_at')
    readonly_fields = ('updated_at',)
    list_display = ('active_provider', 'updated_at')

    def has_add_permission(self, request):
        return not PaymentGatewaySetting.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ['user', 'balance', 'id']
    search_fields = ['user__username', 'user__email']
    readonly_fields = ['balance']
    actions = ['reconcile_selected_wallets']
    change_list_template = 'admin/wallet/wallet/change_list.html'

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                'reconcile/',
                self.admin_site.admin_view(self.reconcile_wallets_view),
                name='wallet_wallet_reconcile',
            ),
        ]
        return custom_urls + urls

    def reconcile_wallets_view(self, request):
        """
        Admin view to run wallet reconciliation across all wallets.
        """
        from wallet.models import Wallet

        if request.method != 'POST':
            messages.error(request, "Reconciliation must be triggered via POST.")
            return redirect('admin:wallet_wallet_changelist')

        fix = request.POST.get('fix') == '1'
        result = Wallet.reconcile_all_wallets(dry_run=not fix)

        msg = (
            f"Reconciliation complete. Wallets checked: {result['total_wallets']}, "
            f"discrepancies: {result['wallets_with_discrepancies']}, "
            f"fixed: {result['wallets_fixed']}."
        )
        messages.info(request, msg)
        return redirect('admin:wallet_wallet_changelist')

    @admin.action(description='Reconcile selected wallets (fix balances)')
    def reconcile_selected_wallets(self, request, queryset):
        """
        Admin action to reconcile wallet balances against transaction sums.
        """
        fixed_count = 0
        for wallet in queryset.select_related('user'):
            result = wallet.verify_balance_integrity()
            if result['is_valid']:
                continue
            wallet.recalculate_balance()
            fixed_count += 1

        self.message_user(
            request,
            f"Reconciliation complete. Wallets fixed: {fixed_count}.",
            level=messages.INFO,
        )

@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ['wallet', 'amount_display', 'transaction_type', 'description_short', 'created_at']
    list_filter = ['transaction_type', 'created_at']
    search_fields = ['wallet__user__username', 'description']
    readonly_fields = ['created_at']
    date_hierarchy = 'created_at'
    
    def amount_display(self, obj):
        """Display amount with color coding"""
        if obj.amount >= 0:
            return f"+ZMW {obj.amount:.2f}"
        else:
            return f"-ZMW {abs(obj.amount):.2f}"
    amount_display.short_description = 'Amount'
    amount_display.admin_order_field = 'amount'
    
    def description_short(self, obj):
        """Display short description"""
        if obj.description:
            return obj.description[:50] + '...' if len(obj.description) > 50 else obj.description
        return '-'
    description_short.short_description = 'Description'

@admin.register(Deposit)
class DepositAdmin(admin.ModelAdmin):
    list_display = ['user', 'amount', 'payment_provider', 'payment_method', 'status', 'created_at', 'transaction_id_short']
    list_filter = ['status', 'payment_provider', 'payment_method', 'created_at']
    search_fields = ['user__username', 'user__email', 'transaction_id']
    readonly_fields = ['created_at', 'updated_at']
    date_hierarchy = 'created_at'
    actions = ['mark_as_completed', 'mark_as_failed', 'mark_as_cancelled']
    
    fieldsets = (
        ('User Information', {
            'fields': ('user', 'wallet')
        }),
        ('Deposit Details', {
            'fields': ('amount', 'payment_provider', 'payment_method', 'status', 'transaction_id')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def transaction_id_short(self, obj):
        """Display short transaction ID"""
        if obj.transaction_id:
            return obj.transaction_id[:20] + '...' if len(obj.transaction_id) > 20 else obj.transaction_id
        return '-'
    transaction_id_short.short_description = 'Transaction ID'
    
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
                description=f"Deposit of ZMW {deposit.amount} via {deposit.get_payment_method_display()}"
            )
            
            # Update deposit status (use update() to bypass clean() validation)
            Deposit.objects.filter(id=deposit.id).update(status='COMPLETED', updated_at=timezone.now())
            deposit.refresh_from_db()

            # Audit log: Deposit completed via admin
            from audit.utils import log_action
            log_action(
                action='deposit_completed',
                user=request.user,
                details={
                    'deposit_id': deposit.id,
                    'amount': str(deposit.amount),
                    'payment_method': deposit.payment_method,
                    'completed_by': 'admin',
                    'new_balance': str(wallet.balance),
                },
                request=request
            )

            from wallet.notifications import notify_deposit_completed
            notify_deposit_completed(deposit)

            count += 1

        self.message_user(request, f'{count} deposit(s) marked as completed.')
    
    @admin.action(description='Mark selected deposits as FAILED')
    def mark_as_failed(self, request, queryset):
        """Mark deposits as FAILED"""
        deposits_to_fail = Deposit.objects.filter(
            id__in=queryset.values_list('id', flat=True),
            status__in=['PENDING', 'PROCESSING']
        )
        deposits = list(deposits_to_fail)
        count = deposits_to_fail.update(status='FAILED', updated_at=timezone.now())

        # Audit log: Deposits failed via admin
        from audit.utils import log_action
        from wallet.notifications import notify_deposit_failed
        for deposit in deposits:
            log_action(
                action='deposit_failed',
                user=request.user,
                details={
                    'deposit_id': deposit.id,
                    'amount': str(deposit.amount),
                    'payment_method': deposit.payment_method,
                    'failed_by': 'admin',
                },
                request=request
            )
            notify_deposit_failed(deposit, 'Marked as failed by admin')

        self.message_user(request, f'{count} deposit(s) marked as failed.')
    
    @admin.action(description='Mark selected deposits as CANCELLED')
    def mark_as_cancelled(self, request, queryset):
        """Mark deposits as CANCELLED"""
        deposits_to_cancel = Deposit.objects.filter(
            id__in=queryset.values_list('id', flat=True),
            status__in=['PENDING', 'PROCESSING']
        )
        deposits = list(deposits_to_cancel)
        count = deposits_to_cancel.update(status='CANCELLED', updated_at=timezone.now())

        # Audit log: Deposits cancelled via admin
        from audit.utils import log_action
        from wallet.notifications import notify_deposit_failed
        for deposit in deposits:
            log_action(
                action='deposit_cancelled',
                user=request.user,
                details={
                    'deposit_id': deposit.id,
                    'amount': str(deposit.amount),
                    'payment_method': deposit.payment_method,
                    'cancelled_by': 'admin',
                },
                request=request
            )
            notify_deposit_failed(deposit, 'Deposit cancelled by admin')

        self.message_user(request, f'{count} deposit(s) marked as cancelled.')

@admin.register(Withdrawal)
class WithdrawalAdmin(admin.ModelAdmin):
    list_display = ['user', 'amount_display', 'payment_method', 'status_display', 'retry_count_display', 'created_at', 'transaction_id_short', 'process_withdrawal_link']
    list_filter = ['status', 'payment_method', 'created_at', 'retry_count']
    search_fields = ['user__username', 'user__email', 'transaction_id', 'gateway_transaction_id', 'account_details']
    readonly_fields = ['created_at', 'updated_at', 'retry_info_display', 'gateway_response_display', 'failure_reason_display']
    change_form_template = 'admin/wallet/withdrawal/change_form.html'
    date_hierarchy = 'created_at'
    list_per_page = 50
    ordering = ['-created_at']
    actions = ['mark_as_completed', 'mark_as_failed', 'mark_as_cancelled', 'process_withdrawals', 'bulk_retry_failed']

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user', 'wallet')
    
    def get_urls(self):
        """Add custom URLs for withdrawal processing"""
        urls = super().get_urls()
        custom_urls = [
            path(
                '<int:withdrawal_id>/process/',
                self.admin_site.admin_view(self.process_withdrawal_view),
                name='wallet_withdrawal_process',
            ),
        ]
        return custom_urls + urls
    
    def process_withdrawal_link(self, obj):
        """Display link to process individual withdrawal"""
        if obj and not obj.is_final and obj.status in ['PENDING', 'PROCESSING']:
            url = reverse('admin:wallet_withdrawal_process', args=[obj.pk])
            return format_html('<a href="{}" class="button">Process</a>', url)
        return '-'
    process_withdrawal_link.short_description = 'Actions'
    
    @staff_member_required
    @transaction.atomic
    def process_withdrawal_view(self, request, withdrawal_id):
        """
        Custom admin view to process individual withdrawal.
        
        Security:
        - Verifies user is support staff
        - Uses atomic transactions
        - Validates withdrawal state before processing
        - Logs all operations
        """
        import logging
        from wallet.payment_manager import get_payment_manager
        from wallet.notifications import (
            notify_withdrawal_processing,
            notify_withdrawal_completed,
            notify_withdrawal_failed,
            notify_withdrawal_retry
        )
        
        logger = logging.getLogger(__name__)
        
        # Security: Verify user is support staff
        if not (request.user.is_staff or request.user.is_superuser or getattr(request.user, 'is_support_staff', False)):
            messages.error(request, 'You do not have permission to process withdrawals.')
            return redirect('admin:wallet_withdrawal_changelist')
        
        # Security: Lock withdrawal to prevent concurrent processing
        try:
            withdrawal = Withdrawal.objects.select_for_update().get(id=withdrawal_id)
        except Withdrawal.DoesNotExist:
            messages.error(request, f'Withdrawal {withdrawal_id} not found.')
            return redirect('admin:wallet_withdrawal_changelist')
        
        # Security: Validate withdrawal state
        if withdrawal.is_final:
            messages.warning(
                request,
                f'Withdrawal {withdrawal.id} is already in final state ({withdrawal.status}) and cannot be processed.'
            )
            return redirect('admin:wallet_withdrawal_change', withdrawal.id)
        
        if withdrawal.status not in ['PENDING', 'PROCESSING']:
            messages.warning(
                request,
                f'Withdrawal {withdrawal.id} is in {withdrawal.status} state and cannot be processed.'
            )
            return redirect('admin:wallet_withdrawal_change', withdrawal.id)
        
        try:
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
                completion = process_withdrawal_and_debit_wallet(
                    withdrawal,
                    {
                        'transaction_id': result.get('transaction_id'),
                        'gateway_response': result.get('gateway_response', {}),
                    },
                )
                if not completion.get('success'):
                    messages.error(
                        request,
                        f'Withdrawal {withdrawal.id} could not be completed: {completion.get("message")}'
                    )
                    return redirect('admin:wallet_withdrawal_change', withdrawal.id)
                
                # Send completion notification
                withdrawal.refresh_from_db()
                wallet = withdrawal.wallet
                notify_withdrawal_completed(withdrawal)
                
                # Audit log: Withdrawal completed via admin
                from audit.utils import log_action
                log_action(
                    action='withdrawal_completed',
                    user=request.user,
                    details={
                        'withdrawal_id': withdrawal.id,
                        'amount': str(withdrawal.amount),
                        'payment_method': withdrawal.payment_method,
                        'transaction_id': result.get('transaction_id'),
                        'completed_by': 'admin',
                        'new_balance': str(wallet.balance),
                    },
                    request=request
                )
                
                logger.info(
                    f'Withdrawal {withdrawal.id} processed successfully via admin by {request.user.username}. '
                    f'Transaction ID: {result.get("transaction_id")}'
                )
                messages.success(
                    request,
                    f'Withdrawal {withdrawal.id} processed successfully. '
                    f'Transaction ID: {result.get("transaction_id", "N/A")}'
                )
            else:
                # Withdrawal failed
                new_retry_count = withdrawal.retry_count + 1
                
                # Determine if we should retry or mark as failed
                if new_retry_count >= withdrawal.max_retry_count:
                    # Max retries exceeded - mark as FAILED
                    Withdrawal.objects.filter(id=withdrawal.id).update(
                        status='FAILED',
                        gateway_response=result.get('gateway_response', {}),
                        failure_reason=result.get('failure_reason', 'Unknown error'),
                        retry_count=new_retry_count,
                        updated_at=timezone.now()
                    )
                    refund_result = refund_withdrawal_reservation(
                        withdrawal,
                        result.get('failure_reason', 'Withdrawal failed'),
                    )
                    
                    # Send failure notification
                    withdrawal.refresh_from_db()
                    notify_withdrawal_failed(withdrawal, result.get('failure_reason', 'Unknown error'))
                    
                    # Audit log: Withdrawal failed via admin
                    from audit.utils import log_action
                    log_action(
                        action='withdrawal_failed',
                        user=request.user,
                        details={
                            'withdrawal_id': withdrawal.id,
                            'amount': str(withdrawal.amount),
                            'payment_method': withdrawal.payment_method,
                            'failure_reason': result.get('failure_reason', 'Unknown error'),
                            'retry_count': new_retry_count,
                            'failed_by': 'admin',
                            'refunded': refund_result['refunded'],
                            'new_balance': str(refund_result['new_balance']),
                        },
                        request=request
                    )
                    
                    logger.warning(
                        f'Withdrawal {withdrawal.id} failed after {new_retry_count} retries. '
                        f'Reason: {result.get("failure_reason")}'
                    )
                    messages.error(
                        request,
                        f'Withdrawal {withdrawal.id} failed after {new_retry_count} retries. '
                        f'Reason: {result.get("failure_reason", "Unknown error")}'
                    )
                else:
                    # Retry later - set back to PENDING
                    Withdrawal.objects.filter(id=withdrawal.id).update(
                        status='PENDING',
                        gateway_response=result.get('gateway_response', {}),
                        failure_reason=result.get('failure_reason', 'Unknown error'),
                        retry_count=new_retry_count,
                        updated_at=timezone.now()
                    )
                    
                    # Send retry notification
                    withdrawal.refresh_from_db()
                    notify_withdrawal_retry(withdrawal, new_retry_count, withdrawal.max_retry_count)
                    
                    logger.info(
                        f'Withdrawal {withdrawal.id} failed, will retry. '
                        f'Retry count: {new_retry_count}/{withdrawal.max_retry_count}. '
                        f'Reason: {result.get("failure_reason")}'
                    )
                    messages.warning(
                        request,
                        f'Withdrawal {withdrawal.id} failed, will retry. '
                        f'Retry count: {new_retry_count}/{withdrawal.max_retry_count}. '
                        f'Reason: {result.get("failure_reason", "Unknown error")}'
                    )
        
        except Exception as e:
            logger.error(
                f'Error processing withdrawal {withdrawal.id} via admin by {request.user.username}: {str(e)}',
                exc_info=True
            )
            
            # Mark as FAILED if error occurred
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
            
            messages.error(
                request,
                f'Error processing withdrawal {withdrawal.id}: {str(e)}'
            )
        
        return redirect('admin:wallet_withdrawal_change', withdrawal.id)
    
    fieldsets = (
        ('User Information', {
            'fields': ('user', 'wallet')
        }),
        ('Withdrawal Details', {
            'fields': ('amount', 'payment_method', 'account_details', 'status', 'transaction_id', 'gateway_transaction_id')
        }),
        ('Retry Information', {
            'fields': ('retry_count', 'max_retry_count', 'retry_info_display'),
            'classes': ('collapse',)
        }),
        ('Gateway Information', {
            'fields': ('gateway_response_display', 'failure_reason_display', 'ip_address', 'user_agent'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def amount_display(self, obj):
        """Display amount with currency formatting"""
        if obj:
            return f"ZMW {obj.amount:,.2f}"
        return "-"
    amount_display.short_description = 'Amount'
    amount_display.admin_order_field = 'amount'
    
    def status_display(self, obj):
        """Display status with color coding"""
        if not obj:
            return "-"
        status_colors = {
            'PENDING': 'orange',
            'PROCESSING': 'blue',
            'COMPLETED': 'green',
            'FAILED': 'red',
            'CANCELLED': 'gray',
        }
        color = status_colors.get(obj.status, 'black')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.get_status_display()
        )
    status_display.short_description = 'Status'
    status_display.admin_order_field = 'status'
    
    def retry_count_display(self, obj):
        """Display retry count with visual indicator"""
        if obj.retry_count == 0:
            return f"0/{obj.max_retry_count}"
        elif obj.retry_count < obj.max_retry_count:
            return f"⚠️ {obj.retry_count}/{obj.max_retry_count}"
        else:
            return f"❌ {obj.retry_count}/{obj.max_retry_count} (Max)"
    retry_count_display.short_description = 'Retries'
    retry_count_display.admin_order_field = 'retry_count'
    
    def transaction_id_short(self, obj):
        """Display short transaction ID"""
        if obj.transaction_id:
            return obj.transaction_id[:20] + '...' if len(obj.transaction_id) > 20 else obj.transaction_id
        elif obj.gateway_transaction_id:
            return obj.gateway_transaction_id[:20] + '...' if len(obj.gateway_transaction_id) > 20 else obj.gateway_transaction_id
        return '-'
    transaction_id_short.short_description = 'Transaction ID'
    
    def retry_info_display(self, obj):
        """Display retry information"""
        if obj:
            info = f"Retry Count: {obj.retry_count} / {obj.max_retry_count}"
            if obj.retry_count >= obj.max_retry_count:
                info += " (Maximum reached)"
            elif obj.retry_count > 0:
                info += f" (Can retry {obj.max_retry_count - obj.retry_count} more times)"
            else:
                info += " (No retries yet)"
            return info
        return "N/A"
    retry_info_display.short_description = 'Retry Information'
    
    def gateway_response_display(self, obj):
        """Display gateway response in readable format"""
        if obj and obj.gateway_response:
            import json
            return json.dumps(obj.gateway_response, indent=2)
        return "No gateway response"
    gateway_response_display.short_description = 'Gateway Response'
    
    def failure_reason_display(self, obj):
        """Display failure reason"""
        if obj and obj.failure_reason:
            return obj.failure_reason
        return "No failure reason"
    failure_reason_display.short_description = 'Failure Reason'
    
    @admin.action(description='Mark selected withdrawals as COMPLETED')
    @transaction.atomic
    def mark_as_completed(self, request, queryset):
        """Mark withdrawals as COMPLETED and debit the wallet."""
        count = 0
        for withdrawal in queryset:
            if withdrawal.status == 'COMPLETED':
                continue  # Already completed
            if withdrawal.status in ['FAILED', 'CANCELLED']:
                continue  # Cannot change from final states

            completion = process_withdrawal_and_debit_wallet(withdrawal)
            if not completion.get('success'):
                continue
            withdrawal.refresh_from_db()
            wallet = withdrawal.wallet

            # Audit log: Withdrawal completed via admin
            from audit.utils import log_action
            log_action(
                action='withdrawal_completed',
                user=request.user,
                details={
                    'withdrawal_id': withdrawal.id,
                    'amount': str(withdrawal.amount),
                    'payment_method': withdrawal.payment_method,
                    'completed_by': 'admin',
                    'new_balance': str(wallet.balance),
                },
                request=request
            )

            from wallet.notifications import notify_withdrawal_completed
            notify_withdrawal_completed(withdrawal)

            count += 1

        self.message_user(request, f'{count} withdrawal(s) marked as completed.')
    
    @admin.action(description='Mark selected withdrawals as FAILED')
    @transaction.atomic
    def mark_as_failed(self, request, queryset):
        """Mark withdrawals as FAILED and reverse any existing debit."""
        withdrawals_to_fail = Withdrawal.objects.filter(
            id__in=queryset.values_list('id', flat=True),
            status__in=['PENDING', 'PROCESSING']
        )
        count = 0

        # Audit log: Withdrawals failed via admin
        from audit.utils import log_action
        from wallet.notifications import notify_withdrawal_failed
        for withdrawal in withdrawals_to_fail:
            Withdrawal.objects.filter(id=withdrawal.id).update(status='FAILED', updated_at=timezone.now())
            refund_result = refund_withdrawal_reservation(withdrawal, 'Withdrawal failed by admin')
            log_action(
                action='withdrawal_failed',
                user=request.user,
                details={
                    'withdrawal_id': withdrawal.id,
                    'amount': str(withdrawal.amount),
                    'payment_method': withdrawal.payment_method,
                    'failed_by': 'admin',
                    'refunded': refund_result['refunded'],
                    'new_balance': str(refund_result['new_balance']),
                },
                request=request
            )
            withdrawal.refresh_from_db()
            notify_withdrawal_failed(withdrawal, 'Withdrawal failed by admin')
            count += 1

        self.message_user(request, f'{count} withdrawal(s) marked as failed.')
    
    @admin.action(description='Mark selected withdrawals as CANCELLED')
    @transaction.atomic
    def mark_as_cancelled(self, request, queryset):
        """Mark withdrawals as CANCELLED and reverse any existing debit."""
        withdrawals_to_cancel = Withdrawal.objects.filter(
            id__in=queryset.values_list('id', flat=True),
            status__in=['PENDING', 'PROCESSING']
        )
        count = 0

        # Audit log: Withdrawals cancelled via admin
        from audit.utils import log_action
        from wallet.notifications import notify_withdrawal_rejected
        for withdrawal in withdrawals_to_cancel:
            Withdrawal.objects.filter(id=withdrawal.id).update(status='CANCELLED', updated_at=timezone.now())
            refund_result = refund_withdrawal_reservation(withdrawal, 'Withdrawal cancelled by admin')
            log_action(
                action='withdrawal_cancelled',
                user=request.user,
                details={
                    'withdrawal_id': withdrawal.id,
                    'amount': str(withdrawal.amount),
                    'payment_method': withdrawal.payment_method,
                    'cancelled_by': 'admin',
                    'refunded': refund_result['refunded'],
                    'new_balance': str(refund_result['new_balance']),
                },
                request=request
            )
            withdrawal.refresh_from_db()
            notify_withdrawal_rejected(withdrawal, 'Withdrawal request rejected by admin')
            count += 1

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
            # Security: Lock withdrawal to prevent concurrent processing
            try:
                withdrawal = Withdrawal.objects.select_for_update().get(id=withdrawal.id)
            except Withdrawal.DoesNotExist:
                skipped_count += 1
                continue
            
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
                    completion = process_withdrawal_and_debit_wallet(
                        withdrawal,
                        {
                            'transaction_id': result['transaction_id'],
                            'gateway_response': result['gateway_response'],
                        },
                    )
                    if not completion.get('success'):
                        failed_count += 1
                        logger.error(
                            f'Withdrawal {withdrawal.id} could not be completed: {completion.get("message")}'
                        )
                        continue
                    
                    completed_count += 1
                    
                    # Send completion notification
                    withdrawal.refresh_from_db()
                    wallet = withdrawal.wallet
                    notify_withdrawal_completed(withdrawal)
                    
                    # Audit log: Withdrawal completed via admin bulk action
                    from audit.utils import log_action
                    log_action(
                        action='withdrawal_completed',
                        user=request.user,
                        details={
                            'withdrawal_id': withdrawal.id,
                            'amount': str(withdrawal.amount),
                            'payment_method': withdrawal.payment_method,
                            'transaction_id': result['transaction_id'],
                            'completed_by': 'admin_bulk_action',
                            'new_balance': str(wallet.balance),
                        },
                        request=request
                    )
                    
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
                        refund_result = refund_withdrawal_reservation(
                            withdrawal,
                            result['failure_reason'],
                        )
                        
                        failed_count += 1
                        
                        # Send failure notification
                        withdrawal.refresh_from_db()
                        notify_withdrawal_failed(withdrawal, result['failure_reason'])
                        
                        # Audit log: Withdrawal failed via admin bulk action
                        from audit.utils import log_action
                        log_action(
                            action='withdrawal_failed',
                            user=request.user,
                            details={
                                'withdrawal_id': withdrawal.id,
                                'amount': str(withdrawal.amount),
                                'payment_method': withdrawal.payment_method,
                                'failure_reason': result['failure_reason'],
                                'retry_count': new_retry_count,
                                'failed_by': 'admin_bulk_action',
                                'refunded': refund_result['refunded'],
                                'new_balance': str(refund_result['new_balance']),
                            },
                            request=request
                        )
                        
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
                    refund_withdrawal_reservation(withdrawal, f'Processing error: {str(e)}')
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
    
    @admin.action(description='Bulk retry failed withdrawals')
    @transaction.atomic
    def bulk_retry_failed(self, request, queryset):
        """
        Reset failed withdrawals back to PENDING status for retry.
        Only works on withdrawals that have failed but haven't exceeded max retry count.
        
        Security: Staff-only, atomic operations, validation before retry
        """
        import logging
        logger = logging.getLogger(__name__)
        
        retried_count = 0
        skipped_count = 0
        
        for withdrawal in queryset:
            # Only retry FAILED withdrawals that haven't exceeded max retry count
            if withdrawal.status != 'FAILED':
                skipped_count += 1
                continue
            
            if withdrawal.retry_count >= withdrawal.max_retry_count:
                skipped_count += 1
                logger.warning(
                    f'Skipping withdrawal {withdrawal.id} - max retry count exceeded '
                    f'({withdrawal.retry_count}/{withdrawal.max_retry_count})'
                )
                continue
            
            # Reset to PENDING for retry
            Withdrawal.objects.filter(id=withdrawal.id).update(
                status='PENDING',
                failure_reason=None,  # Clear previous failure reason
                updated_at=timezone.now()
            )
            
            retried_count += 1
            logger.info(
                f'Withdrawal {withdrawal.id} reset to PENDING for retry by {request.user.username}'
            )
        
        # Report results
        message_parts = []
        if retried_count > 0:
            message_parts.append(f'{retried_count} withdrawal(s) reset to PENDING for retry')
        if skipped_count > 0:
            message_parts.append(f'{skipped_count} withdrawal(s) skipped')
        
        message = f"Bulk retry: {', '.join(message_parts)}."
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
