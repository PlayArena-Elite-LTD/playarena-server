from django.contrib import admin
from .models import Match

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