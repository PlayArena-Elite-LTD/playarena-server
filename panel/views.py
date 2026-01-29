from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.utils import timezone
from django.db import transaction
from django.contrib.auth import get_user_model
from django.http import HttpResponseNotAllowed
from django_ratelimit.decorators import ratelimit

from matches.models import Match, Evidence
from panel.models import Dispute
from wallet.models import Wallet, Transaction
from alert.models import Notification

from accounts.decorators import support_staff_required

User = get_user_model()

@support_staff_required
@ratelimit(key='user', rate='60/h', method='GET', block=True)
def open_disputes(request):
    """Show all open disputes with attend buttons."""
    disputes = Dispute.objects.filter(status='OPEN').order_by('created_at')
    context = {
        'disputes': disputes
    }
    return render(request, 'panel/open_disputes.html', context)

@support_staff_required
@transaction.atomic
@ratelimit(key='user', rate='30/h', method='POST', block=True)
def attend_dispute(request, dispute_id):
    """Assign the current staff to the dispute and mark as pending."""
    dispute = get_object_or_404(Dispute, id=dispute_id)
    if dispute.status != 'OPEN':
        messages.error(request, "This dispute is already assigned or resolved.")
        return redirect('open_disputes')
    dispute.assigned_to = request.user
    dispute.status = 'PENDING'
    dispute.save()

    # Audit log: dispute assigned
    try:
        from audit.utils import log_action, get_user_agent

        log_action(
            action='dispute_assigned',
            user=request.user,
            details={
                'dispute_id': dispute.id,
                'match_id': dispute.match.id,
                'assigned_to_id': request.user.id,
                'assigned_to_username': request.user.username,
                'assigned_by_id': request.user.id,
                'assigned_by_username': request.user.username,
                'ip_address': request.META.get('REMOTE_ADDR', 'unknown'),
                'user_agent': get_user_agent(request),
            },
            request=request,
        )
    except Exception as e:
        import logging

        logging.getLogger(__name__).error(
            f"Failed to create audit log for dispute {dispute.id} assignment: {e}",
            exc_info=True,
        )
    messages.success(request, "You have been assigned to the dispute.")
    return redirect('my_disputes')

@support_staff_required
@ratelimit(key='user', rate='60/h', method='GET', block=True)
def my_disputes(request):
    """Show disputes assigned to the current support staff."""
    # Show only active (non-resolved) disputes assigned to this staff member,
    # ordered by status so OPEN/PENDING appear before anything else.
    disputes = Dispute.objects.filter(
        assigned_to=request.user
    ).exclude(status='RESOLVED').order_by('status', 'created_at')
    context = {
        'disputes': disputes
    }
    return render(request, 'panel/my_disputes.html', context)


@support_staff_required
@ratelimit(key='user', rate='60/h', method='GET', block=True)
def dispute_stats(request):
    """
    Show dispute pattern statistics per user (how many disputes they are involved in).
    
    This helps support staff detect users who frequently appear in disputes.
    """
    from django.db.models import Count, Q
    from matches.models import Match

    # Base queryset of all disputes
    disputes = Dispute.objects.select_related('match', 'match__creator', 'match__joiner')

    # Build per-user stats by looking at match.creator and match.joiner
    # We aggregate on the User model so that each row is a user with counts.
    User = get_user_model()

    user_stats = (
        User.objects.filter(
            Q(created_matches__dispute__isnull=False) |
            Q(joined_matches__dispute__isnull=False)
        )
        .distinct()
        .annotate(
            total_disputes=Count('created_matches__dispute', distinct=True) +
                           Count('joined_matches__dispute', distinct=True),
            open_disputes=Count(
                'created_matches__dispute',
                filter=Q(created_matches__dispute__status='OPEN'),
                distinct=True
            ) + Count(
                'joined_matches__dispute',
                filter=Q(joined_matches__dispute__status='OPEN'),
                distinct=True
            ),
            pending_disputes=Count(
                'created_matches__dispute',
                filter=Q(created_matches__dispute__status__in=['PENDING', 'ESCALATED']),
                distinct=True
            ) + Count(
                'joined_matches__dispute',
                filter=Q(joined_matches__dispute__status__in=['PENDING', 'ESCALATED']),
                distinct=True
            ),
            resolved_disputes=Count(
                'created_matches__dispute',
                filter=Q(created_matches__dispute__status='RESOLVED'),
                distinct=True
            ) + Count(
                'joined_matches__dispute',
                filter=Q(joined_matches__dispute__status='RESOLVED'),
                distinct=True
            ),
        )
        .order_by('-total_disputes', 'username')
    )

    context = {
        'user_stats': user_stats,
    }
    return render(request, 'panel/dispute_stats.html', context)

@support_staff_required
@ratelimit(key='user', rate='60/h', method='GET', block=True)
def dispute_detail(request, dispute_id):
    """Show details for a dispute, options to message users, suspend, or resolve."""
    dispute = get_object_or_404(Dispute, id=dispute_id)
    match = dispute.match

    # Participants for quick access in template
    participants = [match.creator]
    if match.joiner:
        participants.append(match.joiner)

    # Evidence for this match (for dispute investigation)
    evidence_queryset = Evidence.objects.filter(match=match).select_related('user')
    creator_evidence = evidence_queryset.filter(user=match.creator)
    joiner_evidence = evidence_queryset.filter(user=match.joiner) if match.joiner else Evidence.objects.none()
    context = {
        'dispute': dispute,
        'match': match,
        'participants': participants,
        'evidence_list': evidence_queryset,
        'creator_evidence': creator_evidence,
        'joiner_evidence': joiner_evidence,
    }
    return render(request, 'panel/dispute_detail.html', context)

@support_staff_required
@transaction.atomic
@ratelimit(key='user', rate='30/h', method='POST', block=True)
def suspend_user(request, user_id, dispute_id):
    """Suspend a user (set is_active=False) from dispute detail view."""
    user = get_object_or_404(User, id=user_id)
    if not user.is_active:
        messages.info(request, "User is already suspended.")
    else:
        user.is_active = False
        user.save()
        messages.success(request, f"User {user.username} has been suspended.")
    return redirect('dispute_detail', dispute_id=dispute_id)

@support_staff_required
@transaction.atomic
@ratelimit(key='user', rate='30/h', method='POST', block=True)
def resolve_dispute(request, dispute_id):
    """Resolve a dispute, select winner, update wallet, notify participants, and mark as resolved."""
    dispute = get_object_or_404(Dispute, id=dispute_id)
    match = dispute.match

    # Only the assigned support staff can resolve, and only when dispute is PENDING or ESCALATED
    if dispute.status not in ['PENDING', 'ESCALATED'] or dispute.assigned_to != request.user:
        messages.error(request, "You are not allowed to resolve this dispute.")
        return redirect('dispute_detail', dispute_id=dispute_id)

    if request.method == 'POST':
        winner_id = request.POST.get('winner_id')
        notes = request.POST.get('resolution_notes', '')
        if not winner_id:
            messages.error(request, "Please select a winner.")
            return redirect('dispute_detail', dispute_id=dispute_id)
        if str(winner_id) not in [str(getattr(match, 'creator_id')), str(getattr(match, 'joiner_id'))]:
            messages.error(request, "Invalid winner.")
            return redirect('dispute_detail', dispute_id=dispute_id)
        winner = User.objects.get(id=winner_id)
        # Add winnings to winner's wallet
        wallet = Wallet.objects.get(user=winner)
        wallet.balance += match.winnings
        wallet.save()
        # Record wallet transaction
        Transaction.objects.create(
            wallet=wallet,
            amount=match.winnings,
            transaction_type='MATCH_WINNINGS',
            description=f"Winnings from resolving match {match.get_game_display()} dispute"
        )
        # Notify both participants
        Notification.objects.create(
            user=match.creator,
            message=(
                f"Dispute resolved for your {match.get_game_display()} match "
                f"against {match.joiner.username if match.joiner else 'opponent'} for ${match.amount}. "
                f"Support staff selected {winner.username} as the winner; "
                f"${match.winnings} has been processed accordingly."
            ),
        )
        if match.joiner:
            Notification.objects.create(
                user=match.joiner,
                message=(
                    f"Dispute resolved for your {match.get_game_display()} match "
                    f"against {match.creator.username} for ${match.amount}. "
                    f"Support staff selected {winner.username} as the winner; "
                    f"${match.winnings} has been processed accordingly."
                ),
            )
        # Update match & dispute
        match.status = 'COMPLETED'
        match.winner = winner
        match.save()
        dispute.status = 'RESOLVED'
        dispute.resolved_at = timezone.now()
        dispute.resolution_notes = notes
        dispute.save()
        messages.success(request, f"Dispute resolved. {winner.username} is the winner and has been credited.")
        return redirect('my_disputes')
    # On GET, redirect to dispute detail
    return redirect('dispute_detail', dispute_id=dispute_id)


@support_staff_required
@transaction.atomic
@ratelimit(key='user', rate='30/h', method='POST', block=True)
def escalate_dispute(request, dispute_id):
    """
    Escalate a dispute for further review.

    Workflow:
    - Only the assigned support staff can escalate.
    - Only disputes in PENDING state can be escalated.
    - Escalation sets status to ESCALATED and records metadata.
    """
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    dispute = get_object_or_404(Dispute, id=dispute_id)

    if dispute.status != 'PENDING' or dispute.assigned_to != request.user:
        messages.error(request, "You are not allowed to escalate this dispute.")
        return redirect('dispute_detail', dispute_id=dispute_id)

    escalation_reason = request.POST.get('escalation_reason', '').strip()

    dispute.status = 'ESCALATED'
    dispute.escalated_at = timezone.now()
    dispute.escalated_by = request.user
    dispute.escalation_reason = escalation_reason or None
    dispute.save(update_fields=['status', 'escalated_at', 'escalated_by', 'escalation_reason'])

    # Notify participants that the dispute has been escalated
    match = dispute.match
    Notification.objects.create(
        user=match.creator,
        message=(
            f"Your {match.get_game_display()} match dispute against "
            f"{match.joiner.username if match.joiner else 'opponent'} for ${match.amount} "
            "has been escalated for further review by support staff."
        ),
    )
    if match.joiner:
        Notification.objects.create(
            user=match.joiner,
            message=(
                f"Your {match.get_game_display()} match dispute against {match.creator.username} "
                f"for ${match.amount} has been escalated for further review by support staff."
            ),
        )

    messages.success(request, "Dispute has been escalated for further review.")
    return redirect('dispute_detail', dispute_id=dispute.id)


@support_staff_required
@transaction.atomic
@ratelimit(key='user', rate='60/h', method='POST', block=True)
def update_evidence_notes(request, evidence_id):
    """
    Allow support staff to add or update internal notes on an evidence item.

    Security:
    - Staff-only access via decorator
    - POST-only endpoint
    - Notes are stored on Evidence.staff_notes and never shown to regular users
    """
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    evidence = get_object_or_404(Evidence, id=evidence_id)
    dispute = getattr(evidence.match, 'dispute', None)

    if not dispute:
        messages.error(request, "This evidence is not linked to a dispute.")
        return redirect('open_disputes')

    staff_notes = request.POST.get('staff_notes', '').strip()
    evidence.staff_notes = staff_notes or None
    evidence.save(update_fields=['staff_notes'])

    messages.success(request, "Evidence notes updated.")
    return redirect('dispute_detail', dispute_id=dispute.id)