"""Admin controls for the referral program (spec section 7).

Admins can suspend referrers, adjust commission rates (globally via settings or
per-referrer here), and reverse commissions. The commission ledger is
read-only to preserve the immutable audit trail.
"""
from django.contrib import admin, messages
from django.utils import timezone

from . import services
from .models import (
    Referral,
    Referrer,
    ReferralCommissionLedger,
    ReferralWallet,
    ReferralWithdrawal,
)


@admin.register(Referrer)
class ReferrerAdmin(admin.ModelAdmin):
    list_display = ("referral_code", "user", "status", "commission_rate", "created_at")
    list_filter = ("status",)
    search_fields = ("referral_code", "user__username", "user__email")
    list_editable = ("status", "commission_rate")
    readonly_fields = ("created_at", "updated_at")
    actions = ("approve_referrers", "suspend_referrers", "reject_referrers")

    @admin.action(description="Approve selected referrers")
    def approve_referrers(self, request, queryset):
        updated = queryset.update(status=Referrer.Status.APPROVED)
        self.message_user(request, f"{updated} referrer(s) approved.", messages.SUCCESS)

    @admin.action(description="Suspend selected referrers")
    def suspend_referrers(self, request, queryset):
        updated = queryset.update(status=Referrer.Status.SUSPENDED)
        self.message_user(request, f"{updated} referrer(s) suspended.", messages.WARNING)

    @admin.action(description="Reject selected referrers")
    def reject_referrers(self, request, queryset):
        updated = queryset.update(status=Referrer.Status.REJECTED)
        self.message_user(request, f"{updated} referrer(s) rejected.", messages.WARNING)


@admin.register(Referral)
class ReferralAdmin(admin.ModelAdmin):
    list_display = ("referred_user", "referrer", "referral_code", "status", "created_at")
    list_filter = ("status",)
    search_fields = (
        "referred_user__username",
        "referrer__referral_code",
        "referral_code",
    )
    readonly_fields = ("created_at",)
    autocomplete_fields = ("referrer",)


@admin.register(ReferralCommissionLedger)
class ReferralCommissionLedgerAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "referrer",
        "referred_user",
        "platform_fee",
        "commission_rate",
        "commission_amount",
        "status",
        "created_at",
    )
    list_filter = ("status",)
    search_fields = ("referrer__referral_code", "referred_user__username")
    date_hierarchy = "created_at"
    actions = ("reverse_entries",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False  # immutable audit trail

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description="Reverse selected commission entries")
    def reverse_entries(self, request, queryset):
        total = 0
        for entry in queryset:
            total += services.reverse_commission(source_transaction=entry.transaction) \
                if entry.transaction_id else services.reverse_commission(
                    related_match=entry.related_match,
                    related_tournament=entry.related_tournament,
                )
        self.message_user(
            request, f"Reversed {total} commission entr(ies).", messages.SUCCESS
        )


@admin.register(ReferralWallet)
class ReferralWalletAdmin(admin.ModelAdmin):
    list_display = ("user", "balance", "available_balance", "pending_balance", "updated_at")
    search_fields = ("user__username", "user__email")
    readonly_fields = ("updated_at",)


@admin.register(ReferralWithdrawal)
class ReferralWithdrawalAdmin(admin.ModelAdmin):
    list_display = ("id", "referrer", "amount", "status", "payment_reference", "created_at", "processed_at")
    list_filter = ("status",)
    search_fields = ("referrer__referral_code", "payment_reference")
    readonly_fields = ("created_at",)
    actions = ("approve_withdrawals", "mark_paid", "reject_withdrawals")

    @admin.action(description="Approve selected withdrawals")
    def approve_withdrawals(self, request, queryset):
        updated = queryset.filter(status=ReferralWithdrawal.Status.PENDING).update(
            status=ReferralWithdrawal.Status.APPROVED
        )
        self.message_user(request, f"{updated} withdrawal(s) approved.", messages.SUCCESS)

    @admin.action(description="Mark selected withdrawals as paid")
    def mark_paid(self, request, queryset):
        updated = queryset.update(
            status=ReferralWithdrawal.Status.PAID, processed_at=timezone.now()
        )
        self.message_user(request, f"{updated} withdrawal(s) marked paid.", messages.SUCCESS)

    @admin.action(description="Reject selected withdrawals")
    def reject_withdrawals(self, request, queryset):
        updated = queryset.update(status=ReferralWithdrawal.Status.REJECTED)
        self.message_user(request, f"{updated} withdrawal(s) rejected.", messages.WARNING)
