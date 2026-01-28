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
    list_filter = (
        'game',
        'amount',
        'status',
        'privacy',
        'device',
        'created_at',
    )
    search_fields = (
        'creator__username',
        'joiner__username',
        'joining_code',
    )
    readonly_fields = ('joining_code', 'winnings', 'created_at')

    fieldsets = (
        (None, {
            'fields': ('creator', 'joiner', 'game', 'device', 'privacy', 'amount')
        }),
        ('Auto-generated Fields', {
            'fields': ('joining_code', 'winnings', 'status', 'created_at')
        }),
    )


@admin.register(Evidence)
class EvidenceAdmin(admin.ModelAdmin):
    """Admin interface for Evidence model"""
    list_display = ('id', 'match', 'user', 'file_type', 'uploaded_at', 'is_verified')
    list_filter = ('file_type', 'is_verified', 'uploaded_at')
    search_fields = ('match__joining_code', 'user__username', 'description')
    readonly_fields = ('uploaded_at', 'file_size', 'file_hash', 'ip_address', 'user_agent')
    date_hierarchy = 'uploaded_at'
    
    fieldsets = (
        ('Evidence Info', {
            'fields': ('match', 'user', 'file', 'file_type', 'description')
        }),
        ('Security Info', {
            'fields': ('file_size', 'file_hash', 'ip_address', 'user_agent'),
            'classes': ('collapse',)
        }),
        ('Verification', {
            'fields': ('is_verified', 'verified_by', 'verified_at')
        }),
        ('Timestamps', {
            'fields': ('uploaded_at',)
        }),
    )