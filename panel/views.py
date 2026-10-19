from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.db import transaction
from django.contrib.auth import get_user_model

from matches.models import Match, Evidence
from panel.models import Dispute
from alert.models import Notification

from accounts.decorators import support_staff_required

User = get_user_model()

@support_staff_required
def open_disputes(request):
    """Show all open disputes with attend buttons."""
    disputes = Dispute.objects.filter(status='OPEN').order_by('created_at')
    context = {
        'disputes': disputes
    }
    return render(request, 'panel/open_disputes.html', context)

@support_staff_required
@transaction.atomic
def attend_dispute(request, dispute_id):
    """Assign the current staff to the dispute and mark as pending."""
    dispute = get_object_or_404(Dispute, id=dispute_id)
    if dispute.status != 'OPEN':
        messages.error(request, "This dispute is already assigned or resolved.")
        return redirect('open_disputes')
    dispute.assigned_to = request.user
    dispute.status = 'PENDING'
    dispute.save()
    messages.success(request, "You have been assigned to the dispute.")
    return redirect('my_disputes')

@support_staff_required
def my_disputes(request):
    """Show disputes assigned to the current support staff."""
    disputes = Dispute.objects.filter(assigned_to=request.user).order_by('status', 'created_at')
    context = {
        'disputes': disputes
    }
    return render(request, 'panel/my_disputes.html', context)


@support_staff_required
def dispute_stats(request):
    """Show dispute pattern statistics per user."""
    from django.db.models import Count, Q

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
                filter=Q(created_matches__dispute__status='PENDING'),
                distinct=True
            ) + Count(
                'joined_matches__dispute',
                filter=Q(joined_matches__dispute__status='PENDING'),
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

    return render(request, 'panel/dispute_stats.html', {
        'user_stats': user_stats,
    })


@support_staff_required
def dispute_detail(request, dispute_id):
    """Show details for a dispute, options to message users, suspend, or resolve."""
    dispute = get_object_or_404(Dispute, id=dispute_id)
    match = dispute.match
    participants = [match.creator]
    if match.joiner:
        participants.append(match.joiner)
    
    # Get evidence for this match
    evidence_queryset = Evidence.objects.filter(match=match).select_related('user').order_by('-uploaded_at')
    evidence_list = list(evidence_queryset)
    creator_evidence = list(evidence_queryset.filter(user=match.creator))
    joiner_evidence = []
    if match.joiner:
        joiner_evidence = list(evidence_queryset.filter(user=match.joiner))
    
    context = {
        'dispute': dispute,
        'match': match,
        'participants': participants,
        'evidence_list': evidence_list,
        'creator_evidence': creator_evidence,
        'joiner_evidence': joiner_evidence,
    }
    return render(request, 'panel/dispute_detail.html', context)

@support_staff_required
@transaction.atomic
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
def resolve_dispute(request, dispute_id):
    """Resolve a dispute, select winner, update wallet, notify participants, and mark as resolved."""
    dispute = get_object_or_404(Dispute, id=dispute_id)
    match = dispute.match

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
        from matches.settlement import settle_match
        match = settle_match(match, winner=winner)
        # Notify both participants
        Notification.objects.create(
            user=match.creator,
            message=f"Dispute for match {match.get_game_display()} resolved. Winner: {winner.username}."
        )
        if match.joiner:
            Notification.objects.create(
                user=match.joiner,
                message=f"Dispute for match {match.get_game_display()} resolved. Winner: {winner.username}."
            )
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
def escalate_dispute(request, dispute_id):
    """Escalate a dispute for senior review."""
    dispute = get_object_or_404(Dispute, id=dispute_id)

    if dispute.status == 'RESOLVED':
        messages.error(request, "Cannot escalate a resolved dispute.")
        return redirect('dispute_detail', dispute_id=dispute_id)

    dispute.status = 'ESCALATED'
    dispute.escalated_at = timezone.now()
    dispute.escalated_by = request.user
    if request.method == 'POST':
        dispute.escalation_reason = request.POST.get('escalation_reason', '')
    dispute.save()

    messages.success(request, "Dispute escalated successfully.")
    return redirect('dispute_detail', dispute_id=dispute_id)


@support_staff_required
@transaction.atomic
def update_evidence_notes(request, evidence_id):
    """Update evidence description and verification status from the dispute panel."""
    evidence = get_object_or_404(Evidence, id=evidence_id)

    if request.method == 'POST':
        evidence.description = request.POST.get('description', evidence.description or '')
        if request.POST.get('is_verified') == 'on':
            evidence.is_verified = True
            evidence.verified_by = request.user
            evidence.verified_at = timezone.now()
        evidence.save()

        try:
            dispute_id = evidence.match.dispute.id
        except Dispute.DoesNotExist:
            return redirect('open_disputes')

        messages.success(request, "Evidence updated successfully.")
        return redirect('dispute_detail', dispute_id=dispute_id)

    return JsonResponse({'status': 'error', 'message': 'Invalid request'}, status=400)
