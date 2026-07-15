from django.contrib import admin
from django.contrib import messages
from django.utils.html import format_html, format_html_join
from django.urls import reverse
from django.utils import timezone
from .models import Dispute


@admin.register(Dispute)
class DisputeAdmin(admin.ModelAdmin):
    """Enhanced admin interface for Dispute model"""
    list_display = [
        'id',
        'match_info',
        'status_display',
        'assigned_to',
        'created_at',
        'resolved_at',
        'action_links'
    ]
    list_filter = ['status', 'created_at', 'resolved_at', 'assigned_to']
    search_fields = [
        'match__joining_code',
        'match__creator__username',
        'match__joiner__username',
        'assigned_to__username',
        'resolution_notes'
    ]
    readonly_fields = ['created_at', 'resolved_at']
    date_hierarchy = 'created_at'
    list_per_page = 25
    actions = ['mark_as_open', 'mark_as_pending', 'mark_as_resolved']
    
    fieldsets = (
        ('Dispute Information', {
            'fields': ('match', 'status', 'created_at')
        }),
        ('Assignment', {
            'fields': ('assigned_to',)
        }),
        ('Resolution', {
            'fields': ('resolution_notes', 'resolved_at'),
            'classes': ('collapse',)
        }),
    )
    
    def match_info(self, obj):
        """Display match information with link"""
        match = obj.match
        match_url = reverse('admin:matches_match_change', args=[match.id])
        return format_html(
            '<a href="{}">{}</a><br/>'
            '<small>Game: {} | Amount: ZMW {} | Code: {}</small>',
            match_url,
            match,
            match.get_game_display(),
            match.amount,
            match.joining_code
        )
    match_info.short_description = 'Match'
    match_info.admin_order_field = 'match__created_at'
    
    def status_display(self, obj):
        """Display status with color coding"""
        colors = {
            'OPEN': '#f56565',      # Red
            'PENDING': '#ed8936',   # Orange
            'RESOLVED': '#48bb78',  # Green
        }
        color = colors.get(obj.status, '#718096')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.get_status_display()
        )
    status_display.short_description = 'Status'
    status_display.admin_order_field = 'status'
    
    def action_links(self, obj):
        """Display action links"""
        links = []
        
        if obj.status == 'OPEN':
            links.append((reverse('attend_dispute', args=[obj.id]), 'Attend'))
        elif obj.status in ['PENDING', 'ESCALATED']:
            links.append((reverse('dispute_detail', args=[obj.id]), 'View Details'))
        
        if obj.status != 'RESOLVED':
            links.append((reverse('escalate_dispute', args=[obj.id]), 'Escalate'))
        
        if not links:
            return '-'

        return format_html_join(
            '',
            '<a href="{}" class="button">{}</a>',
            links
        )
    
    action_links.short_description = 'Actions'
    
    def get_queryset(self, request):
        """Optimize queryset with select_related"""
        qs = super().get_queryset(request)
        return qs.select_related('match', 'match__creator', 'match__joiner', 'assigned_to')
    
    def get_list_display(self, request):
        """Customize list display based on user permissions"""
        display = list(super().get_list_display(request))
        return display
    
    @admin.action(description='Mark selected disputes as OPEN')
    def mark_as_open(self, request, queryset):
        """Bulk action to mark disputes as open"""
        count = queryset.update(status='OPEN', assigned_to=None)
        self.message_user(
            request,
            f'Successfully marked {count} dispute(s) as OPEN.',
            messages.SUCCESS
        )
    
    @admin.action(description='Mark selected disputes as PENDING')
    def mark_as_pending(self, request, queryset):
        """Bulk action to mark disputes as pending"""
        count = queryset.update(status='PENDING', assigned_to=request.user)
        self.message_user(
            request,
            f'Successfully marked {count} dispute(s) as PENDING and assigned to you.',
            messages.SUCCESS
        )
    
    @admin.action(description='Mark selected disputes as RESOLVED')
    def mark_as_resolved(self, request, queryset):
        """Bulk action to mark disputes as resolved"""
        count = queryset.update(
            status='RESOLVED',
            resolved_at=timezone.now()
        )
        self.message_user(
            request,
            f'Successfully marked {count} dispute(s) as RESOLVED.',
            messages.SUCCESS
        )
