from django.contrib import admin
from django.contrib import messages
from django.db.models import Count
from django.utils.html import format_html, format_html_join
from django.urls import reverse
from django.utils import timezone
from django.utils.timesince import timesince
from .models import Dispute


@admin.register(Dispute)
class DisputeAdmin(admin.ModelAdmin):
    """Enhanced admin interface for Dispute model"""
    change_list_template = 'admin/panel/dispute/change_list.html'
    list_display = [
        'id',
        'match_summary',
        'status_display',
        'assigned_display',
        'created_age',
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
    readonly_fields = ['created_at', 'resolved_at', 'escalated_at', 'escalated_by']
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
        ('Escalation', {
            'fields': ('escalated_at', 'escalated_by', 'escalation_reason'),
            'classes': ('collapse',)
        }),
    )
    
    def match_summary(self, obj):
        """Display match information with link"""
        match = obj.match
        match_url = reverse('admin:matches_match_change', args=[match.id])
        participants = match.creator.username
        if match.joiner:
            participants = f'{participants} vs {match.joiner.username}'

        return format_html(
            '<div class="dispute-match">'
            '<a class="dispute-match__title" href="{}">{}</a>'
            '<div class="dispute-match__meta">'
            '<span>{}</span><span>ZMW {}</span><span>Code {}</span>'
            '</div>'
            '<div class="dispute-match__players">{}</div>'
            '</div>',
            match_url,
            match,
            match.get_game_display(),
            match.amount,
            match.joining_code,
            participants
        )
    match_summary.short_description = 'Match'
    match_summary.admin_order_field = 'match__created_at'
    
    def status_display(self, obj):
        """Display status with color coding"""
        status_classes = {
            'OPEN': 'open',
            'PENDING': 'pending',
            'ESCALATED': 'escalated',
            'RESOLVED': 'resolved',
        }
        return format_html(
            '<span class="dispute-status dispute-status--{}">{}</span>',
            status_classes.get(obj.status, 'default'),
            obj.get_status_display()
        )
    status_display.short_description = 'Status'
    status_display.admin_order_field = 'status'

    def assigned_display(self, obj):
        """Display assignee in a compact staff chip."""
        if not obj.assigned_to:
            return format_html(
                '<span class="dispute-assignee dispute-assignee--empty">{}</span>',
                'Unassigned'
            )

        return format_html(
            '<span class="dispute-assignee"><span>{}</span><strong>{}</strong></span>',
            obj.assigned_to.username[:1].upper(),
            obj.assigned_to.username
        )
    assigned_display.short_description = 'Assigned'
    assigned_display.admin_order_field = 'assigned_to__username'

    def created_age(self, obj):
        """Show how long the dispute has been waiting."""
        return format_html(
            '<span class="dispute-age">{} ago</span>',
            timesince(obj.created_at, timezone.now())
        )
    created_age.short_description = 'Age'
    created_age.admin_order_field = 'created_at'
    
    def action_links(self, obj):
        """Display action links"""
        links = []
        
        if obj.status == 'OPEN':
            links.append((reverse('attend_dispute', args=[obj.id]), 'primary', 'Attend'))
        elif obj.status == 'PENDING':
            links.append((reverse('dispute_detail', args=[obj.id]), 'secondary', 'Review'))
        elif obj.status == 'ESCALATED':
            links.append((reverse('dispute_detail', args=[obj.id]), 'warning', 'Review Escalation'))
        
        if obj.status in ['OPEN', 'PENDING']:
            links.append((reverse('escalate_dispute', args=[obj.id]), 'warning', 'Escalate'))
        
        if not links:
            return format_html('<span class="dispute-actions__empty">{}</span>', 'Resolved')

        actions = format_html_join(
            '',
            '<a href="{}" class="dispute-action dispute-action--{}">{}</a>',
            links
        )
        return format_html('<div class="dispute-actions">{}</div>', actions)
    
    action_links.short_description = 'Actions'

    def changelist_view(self, request, extra_context=None):
        """Add dispute status totals above the admin changelist."""
        status_counts = {
            row['status']: row['total']
            for row in self.model.objects.values('status').annotate(total=Count('id'))
        }
        extra_context = {
            **(extra_context or {}),
            'dispute_summary': {
                'total': sum(status_counts.values()),
                'open': status_counts.get('OPEN', 0),
                'pending': status_counts.get('PENDING', 0),
                'escalated': status_counts.get('ESCALATED', 0),
                'resolved': status_counts.get('RESOLVED', 0),
            },
        }
        return super().changelist_view(request, extra_context=extra_context)
    
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
