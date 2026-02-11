from django.contrib import admin
from django.contrib.auth.views import LoginView
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.shortcuts import redirect
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from datetime import timedelta
from django.db.models import Sum, Count, Q
from django.contrib.auth import get_user_model

User = get_user_model()

# Use default admin site but customize it
admin.site.site_header = "PlayyArena Administration"
admin.site.site_title = "PlayyArena Admin"
admin.site.index_title = "Dashboard Overview"

# Override the index view
def custom_admin_index(request, extra_context=None):
    """
    Custom admin dashboard with statistics
    """
    # Calculate statistics
    total_users = User.objects.count()
    
    # Get match statistics
    try:
        from matches.models import Match
        total_matches = Match.objects.count()
        recent_matches = Match.objects.filter(
            created_at__gte=timezone.now() - timedelta(days=1)
        ).count()
    except (ImportError, Exception):
        total_matches = 0
        recent_matches = 0
    
    # Get wallet statistics
    try:
        from wallet.models import Wallet, Transaction
        total_wallet_balance = Wallet.objects.aggregate(
            total=Sum('balance')
        )['total'] or 0
        
        recent_transactions = Transaction.objects.filter(
            created_at__gte=timezone.now() - timedelta(days=1)
        ).aggregate(
            total=Sum('amount')
        )['total'] or 0
    except (ImportError, Exception):
        total_wallet_balance = 0
        recent_transactions = 0
    
    # Get dispute statistics
    try:
        from panel.models import Dispute
        open_disputes = Dispute.objects.filter(status='OPEN').count()
        pending_disputes = Dispute.objects.filter(status='PENDING').count()
        total_disputes = Dispute.objects.count()
        resolved_disputes = Dispute.objects.filter(status='RESOLVED').count()
    except (ImportError, Exception):
        open_disputes = 0
        pending_disputes = 0
        total_disputes = 0
        resolved_disputes = 0
    
    # Get message statistics
    try:
        from messenger.models import Message
        total_messages = Message.objects.count()
    except (ImportError, Exception):
        total_messages = 0
    
    # Get notification statistics
    try:
        from alert.models import Notification
        total_notifications = Notification.objects.count()
    except (ImportError, Exception):
        total_notifications = 0
    
    # Recent users (last 7 days)
    recent_users = User.objects.filter(
        date_joined__gte=timezone.now() - timedelta(days=7)
    ).count()
    
    context = {
        **admin.site.each_context(request),
        'total_users': total_users,
        'total_matches': total_matches,
        'total_wallet_balance': total_wallet_balance,
        'open_disputes': open_disputes,
        'total_messages': total_messages,
        'total_notifications': total_notifications,
        'recent_users': recent_users,
        'recent_matches': recent_matches,
        'recent_transactions': recent_transactions,
        'pending_disputes': pending_disputes,
        'total_disputes': total_disputes,
        'resolved_disputes': resolved_disputes,
        **(extra_context or {}),
    }
    
    request.current_app = admin.site.name
    
    return TemplateResponse(
        request,
        'admin/index.html',
        context,
    )

# Override the admin index view
admin.site.index = custom_admin_index


class AdminLoginView(LoginView):
    """
    Custom admin login view that properly handles redirects
    """
    template_name = 'admin/login.html'
    redirect_field_name = REDIRECT_FIELD_NAME
    
    def dispatch(self, request, *args, **kwargs):
        # If user is already authenticated and is staff, redirect to admin
        if request.user.is_authenticated:
            if request.user.is_staff:
                redirect_to = request.GET.get(
                    self.redirect_field_name,
                    reverse('admin:index')
                )
                # Security check for redirect URL
                if url_has_allowed_host_and_scheme(redirect_to, allowed_hosts=request.get_host()):
                    return redirect(redirect_to)
                return redirect('admin:index')
            else:
                # Non-staff user trying to access admin - redirect to regular dashboard
                return redirect('dashboard')
        return super().dispatch(request, *args, **kwargs)
    
    def form_valid(self, form):
        """If the form is valid, redirect to the supplied URL or admin index."""
        from django.contrib.auth import login
        from django.contrib import messages
        
        user = form.get_user()
        
        # Log the user in
        login(self.request, user)
        
        # Check if user is staff
        if not user.is_staff:
            # Non-staff user - redirect to regular dashboard with message
            messages.warning(self.request, 'You do not have permission to access the admin panel.')
            return redirect('dashboard')
        
        # Staff user - proceed with admin redirect
        redirect_to = self.request.POST.get(
            self.redirect_field_name,
            self.request.GET.get(self.redirect_field_name, '')
        )
        
        # Security check for redirect URL
        if redirect_to and url_has_allowed_host_and_scheme(
            redirect_to, allowed_hosts=self.request.get_host()
        ):
            return redirect(redirect_to)
        
        # Default to admin index
        return redirect('admin:index')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            **admin.site.each_context(self.request),
            'title': 'PlayyArena Admin Login',
            'app_path': self.request.get_full_path(),
            'username': self.request.user.get_username(),
        })
        return context


# Override admin login view
admin.site.login = AdminLoginView.as_view()


def admin_logout_view(request):
    """
    Custom admin logout view that ensures complete session clearing.
    This prevents admins from staying logged in after logout.
    """
    from django.contrib.auth import logout
    from django.contrib import messages
    from django.shortcuts import redirect
    from django.conf import settings
    
    # Store message before logout (since logout clears session)
    messages.success(request, 'You have been logged out successfully.')
    
    # Logout the user (this also flushes the session internally)
    logout(request)
    
    # Create a response to ensure cookies are cleared
    response = redirect('admin:login')
    
    # Explicitly delete session cookie to ensure it's removed from browser
    # This prevents any session persistence after logout
    session_cookie_name = getattr(settings, 'SESSION_COOKIE_NAME', 'sessionid')
    response.delete_cookie(
        session_cookie_name,
        path=getattr(settings, 'SESSION_COOKIE_PATH', '/'),
        domain=getattr(settings, 'SESSION_COOKIE_DOMAIN', None)
    )
    
    return response


# Override admin logout view
admin.site.logout = admin_logout_view

# Export admin_site alias for compatibility
admin_site = admin.site

