from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'action', 'user', 'ip_address', 'short_details')
    list_filter = ('action', 'timestamp', 'user')
    search_fields = ('user__username', 'user__email', 'action', 'details')
    date_hierarchy = 'timestamp'
    readonly_fields = ('timestamp', 'user', 'action', 'details', 'ip_address', 'user_agent')
    ordering = ('-timestamp',)
    list_select_related = ('user',)

    def short_details(self, obj):
        if not obj.details:
            return '-'
        return obj.details[:80] + '...' if len(obj.details) > 80 else obj.details

    short_details.short_description = 'Details'
