from django.contrib import admin
from .models import Match, Evidence

@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'creator',
        'joiner',
        'game',
        'amount',
        'winnings',
        'status',
        'privacy',
        'device',
        'joining_code',
        'created_at',
    )


@admin.register(Evidence)
class EvidenceAdmin(admin.ModelAdmin):
    """Admin interface for Evidence model with security-focused defaults."""

    list_display = (
        'id',
        'match',
        'user',
        'file_type',
        'uploaded_at',
        'is_verified',
        'file_size_mb_display',
    )

    list_filter = (
        'file_type',
        'is_verified',
        'uploaded_at',
        'match__game',
    )

    search_fields = (
        'match__id',
        'match__creator__username',
        'match__joiner__username',
        'user__username',
        'description',
        'ip_address',
        'user_agent',
    )

    readonly_fields = (
        'match',
        'user',
        'file',
        'file_size',
        'file_hash',
        'ip_address',
        'user_agent',
        'uploaded_at',
    )

    fieldsets = (
        ('Evidence Info', {
            'fields': (
                'match',
                'user',
                'file',
                'file_type',
                'uploaded_at',
                'description',
            )
        }),
        ('Security Metadata', {
            'fields': (
                'file_size',
                'file_hash',
                'ip_address',
                'user_agent',
            )
        }),
        ('Verification', {
            'fields': (
                'is_verified',
                'verified_by',
                'verified_at',
            )
        }),
    )

    def file_size_mb_display(self, obj):
        """Human-readable file size for admin list."""
        return f"{obj.file_size_mb:.2f} MB" if obj.file_size else "0 MB"

    file_size_mb_display.short_description = "File Size"