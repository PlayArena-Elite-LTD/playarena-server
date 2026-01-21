from django.contrib import admin
from django.db import transaction
from django.utils import timezone
from .models import Wallet, Transaction, Deposit, Withdrawal

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
    actions = ['mark_as_completed', 'mark_as_failed', 'mark_as_cancelled']
    
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
