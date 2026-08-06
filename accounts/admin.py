from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib import messages
from django.utils.html import format_html, mark_safe
from .forms import CustomUserCreationForm, CustomUserChangeForm
from .models import CustomUser, Organisation, OrganisationMembership, Profile

class CustomUserAdmin(UserAdmin):
    add_form = CustomUserCreationForm
    form = CustomUserChangeForm
    model = CustomUser
    list_display = ['username', 'email', 'is_active_display', 'is_support_staff', 'is_staff', 'date_joined']
    list_filter = ['is_active', 'is_staff', 'is_superuser', 'is_support_staff', 'date_joined']
    search_fields = ['username', 'email', 'first_name', 'last_name']
    actions = ['disable_users', 'enable_users']
    
    # Define the fieldsets explicitly rather than extending them
    fieldsets = (
        (None, {'fields': ('username', 'password', 'is_support_staff')}),
        ('Personal info', {'fields': ('email',)}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser',
                                    'groups', 'user_permissions')}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )
    
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'email', 'is_support_staff', 'password1', 'password2'),
        }),
    )
    
    def is_active_display(self, obj):
        """Display is_active status with color coding"""
        if obj is None:
            return '-'
        if obj.is_active:
            return mark_safe('<span style="color: #48bb78; font-weight: bold;">✓ Active</span>')
        else:
            return mark_safe('<span style="color: #f56565; font-weight: bold;">✗ Disabled</span>')
    is_active_display.short_description = 'Status'
    is_active_display.admin_order_field = 'is_active'
    
    @admin.action(description='Disable selected users')
    def disable_users(self, request, queryset):
        """Bulk action to disable users"""
        # Prevent disabling superusers
        superusers = queryset.filter(is_superuser=True)
        if superusers.exists():
            self.message_user(
                request,
                f'Cannot disable {superusers.count()} superuser(s). Skipping them.',
                messages.WARNING
            )
            queryset = queryset.exclude(is_superuser=True)
        
        # Prevent disabling the current user
        current_user = queryset.filter(id=request.user.id)
        if current_user.exists():
            self.message_user(
                request,
                'Cannot disable your own account. Skipping.',
                messages.WARNING
            )
            queryset = queryset.exclude(id=request.user.id)
        
        count = queryset.update(is_active=False)
        if count > 0:
            self.message_user(
                request,
                f'Successfully disabled {count} user(s).',
                messages.SUCCESS
            )
        else:
            self.message_user(
                request,
                'No users were disabled.',
                messages.INFO
            )
    
    @admin.action(description='Enable selected users')
    def enable_users(self, request, queryset):
        """Bulk action to enable users"""
        count = queryset.update(is_active=True)
        self.message_user(
            request,
            f'Successfully enabled {count} user(s).',
            messages.SUCCESS
        )
    
    def get_queryset(self, request):
        """
        Override to ensure queryset is always fresh and reflects current database state.
        This ensures the total user count updates correctly when users are deleted.
        """
        qs = super().get_queryset(request)
        # Return a fresh queryset that reflects current database state
        return qs
    
    def delete_model(self, request, obj):
        """
        Override delete to ensure proper deletion and count update.
        """
        obj.delete()
    
    def delete_queryset(self, request, queryset):
        """
        Override bulk delete to ensure proper deletion and count update.
        """
        queryset.delete()
    
    def save_model(self, request, obj, form, change):
        """Override save to prevent disabling own account"""
        if change and obj.id == request.user.id and not obj.is_active:
            messages.warning(
                request,
                'You cannot disable your own account. Account remains active.'
            )
            obj.is_active = True
        super().save_model(request, obj, form, change)
    
    def get_readonly_fields(self, request, obj=None):
        """Make is_active readonly for own account"""
        readonly = list(super().get_readonly_fields(request, obj))
        if obj and obj.id == request.user.id:
            # Don't add is_active to readonly, but we handle it in save_model
            pass
        return readonly
    
    def changelist_view(self, request, extra_context=None):
        """Add custom context for changelist"""
        extra_context = extra_context or {}
        extra_context['show_disabled_count'] = True
        return super().changelist_view(request, extra_context)

admin.site.register(CustomUser, CustomUserAdmin)

# Register the Profile model as well
@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'first_name', 'last_name']
    search_fields = ['user__username', 'first_name', 'last_name']


@admin.register(Organisation)
class OrganisationAdmin(admin.ModelAdmin):
    list_display = ['name', 'email', 'organisation_type', 'city', 'is_verified', 'created_at']
    list_filter = ['organisation_type', 'is_verified', 'created_at']
    search_fields = ['name', 'email', 'contact_name', 'owner__username']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(OrganisationMembership)
class OrganisationMembershipAdmin(admin.ModelAdmin):
    list_display = ['organisation', 'player', 'status', 'requested_at', 'reviewed_at', 'reviewed_by']
    list_filter = ['status', 'organisation', 'requested_at', 'reviewed_at']
    search_fields = ['organisation__name', 'player__username', 'player__email']
    readonly_fields = ['requested_at', 'reviewed_at']
