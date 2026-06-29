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
    now = timezone.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = now - timedelta(days=7)

    # Calculate statistics
    total_users = User.objects.count()
    staff_users = User.objects.filter(Q(is_staff=True) | Q(is_support_staff=True)).count()
    active_users = User.objects.filter(is_active=True).count()
    
    # Get match statistics
    try:
        from matches.models import Match
        total_matches = Match.objects.count()
        recent_matches = Match.objects.filter(
            created_at__gte=today_start
        ).count()
        open_matches = Match.objects.filter(status='OPEN').count()
        joined_matches = Match.objects.filter(status='JOINED').count()
        completed_matches = Match.objects.filter(status='COMPLETED').count()
        disputed_matches = Match.objects.filter(status='DISPUTED').count()
        top_games = list(
            Match.objects.values('game')
            .annotate(total=Count('id'))
            .order_by('-total')[:4]
        )
        game_labels = dict(Match.GAME_CHOICES)
        for game in top_games:
            game['label'] = game_labels.get(game['game'], game['game'])
    except (ImportError, Exception):
        total_matches = 0
        recent_matches = 0
        open_matches = 0
        joined_matches = 0
        completed_matches = 0
        disputed_matches = 0
        top_games = []
    
    # Get wallet statistics
    try:
        from wallet.models import Deposit, Transaction, Wallet, Withdrawal
        total_wallet_balance = Wallet.objects.aggregate(
            total=Sum('balance')
        )['total'] or 0
        
        recent_transactions = Transaction.objects.filter(
            created_at__gte=today_start
        ).aggregate(
            total=Sum('amount')
        )['total'] or 0
        today_credits = Transaction.objects.filter(
            created_at__gte=today_start,
            amount__gt=0,
        ).aggregate(total=Sum('amount'))['total'] or 0
        today_debits_raw = Transaction.objects.filter(
            created_at__gte=today_start,
            amount__lt=0,
        ).aggregate(total=Sum('amount'))['total'] or 0
        today_debits = abs(today_debits_raw)
        pending_deposits = Deposit.objects.filter(status__in=['PENDING', 'PROCESSING']).count()
        pending_withdrawals = Withdrawal.objects.filter(status__in=['PENDING', 'PROCESSING']).count()
        failed_payments = (
            Deposit.objects.filter(status='FAILED').count()
            + Withdrawal.objects.filter(status='FAILED').count()
        )
    except (ImportError, Exception):
        total_wallet_balance = 0
        recent_transactions = 0
        today_credits = 0
        today_debits = 0
        pending_deposits = 0
        pending_withdrawals = 0
        failed_payments = 0
    
    # Get dispute statistics
    try:
        from panel.models import Dispute
        open_disputes = Dispute.objects.filter(status='OPEN').count()
        pending_disputes = Dispute.objects.filter(status='PENDING').count()
        escalated_disputes = Dispute.objects.filter(status='ESCALATED').count()
        total_disputes = Dispute.objects.count()
        resolved_disputes = Dispute.objects.filter(status='RESOLVED').count()
        recent_disputes = Dispute.objects.select_related(
            'match',
            'match__creator',
            'match__joiner',
            'assigned_to',
        ).order_by('-created_at')[:5]
    except (ImportError, Exception):
        open_disputes = 0
        pending_disputes = 0
        escalated_disputes = 0
        total_disputes = 0
        resolved_disputes = 0
        recent_disputes = []
    
    # Get message statistics
    try:
        from messenger.models import Message
        total_messages = Message.objects.count()
        messages_today = Message.objects.filter(created_at__gte=today_start).count()
    except (ImportError, Exception):
        total_messages = 0
        messages_today = 0
    
    # Get notification statistics
    try:
        from alert.models import Notification
        total_notifications = Notification.objects.count()
        notifications_today = Notification.objects.filter(created_at__gte=today_start).count()
    except (ImportError, Exception):
        total_notifications = 0
        notifications_today = 0
    
    # Recent users (last 7 days)
    recent_users = User.objects.filter(
        date_joined__gte=week_start
    ).count()
    latest_users = User.objects.order_by('-date_joined')[:5]
    
    context = {
        **admin.site.each_context(request),
        'title': 'Dashboard',
        'app_list': admin.site.get_app_list(request),
        'total_users': total_users,
        'staff_users': staff_users,
        'active_users': active_users,
        'total_matches': total_matches,
        'open_matches': open_matches,
        'joined_matches': joined_matches,
        'completed_matches': completed_matches,
        'disputed_matches': disputed_matches,
        'top_games': top_games,
        'total_wallet_balance': total_wallet_balance,
        'today_credits': today_credits,
        'today_debits': today_debits,
        'pending_deposits': pending_deposits,
        'pending_withdrawals': pending_withdrawals,
        'failed_payments': failed_payments,
        'open_disputes': open_disputes,
        'escalated_disputes': escalated_disputes,
        'recent_disputes': recent_disputes,
        'total_messages': total_messages,
        'messages_today': messages_today,
        'total_notifications': total_notifications,
        'notifications_today': notifications_today,
        'recent_users': recent_users,
        'latest_users': latest_users,
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
