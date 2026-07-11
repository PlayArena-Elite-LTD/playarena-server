from django.shortcuts import render
from django.contrib.auth import get_user_model
from django.db.models import Sum
from django.utils import timezone
from datetime import timedelta

from accounts.decorators import support_staff_required
from matches.models import Match
from wallet.models import Wallet, Deposit, Withdrawal
from panel.models import Dispute

User = get_user_model()


@support_staff_required
def dashboard(request):
    """Admin panel overview: KPI cards across users, matches, wallet, and disputes."""
    week_start = timezone.now() - timedelta(days=7)

    total_users = User.objects.count()
    active_users = User.objects.filter(is_active=True).count()
    recent_users = User.objects.filter(date_joined__gte=week_start).count()

    total_matches = Match.objects.count()
    open_matches = Match.objects.filter(status='OPEN').count()
    disputed_matches = Match.objects.filter(status='DISPUTED').count()

    total_wallet_balance = Wallet.objects.aggregate(total=Sum('balance'))['total'] or 0
    pending_deposits = Deposit.objects.filter(status__in=['PENDING', 'PROCESSING']).count()
    pending_withdrawals = Withdrawal.objects.filter(status__in=['PENDING', 'PROCESSING']).count()

    open_disputes = Dispute.objects.filter(status='OPEN').count()
    escalated_disputes = Dispute.objects.filter(status='ESCALATED').count()

    context = {
        'total_users': total_users,
        'active_users': active_users,
        'recent_users': recent_users,
        'total_matches': total_matches,
        'open_matches': open_matches,
        'disputed_matches': disputed_matches,
        'total_wallet_balance': total_wallet_balance,
        'pending_deposits': pending_deposits,
        'pending_withdrawals': pending_withdrawals,
        'open_disputes': open_disputes,
        'escalated_disputes': escalated_disputes,
    }
    return render(request, 'panel/dashboard.html', context)
