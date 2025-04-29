from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.utils import timezone
from django.db import transaction
from django.contrib.auth import get_user_model

from matches.models import Match
from panel.models import Dispute
from wallet.models import Wallet, Transaction
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
def dispute_detail(request, dispute_id):
    """Show details for a dispute, options to message users, suspend, or resolve."""
    dispute = get_object_or_404(Dispute, id=dispute_id)
    match = dispute.match
    participants = [match.creator]
    if match.joiner:
        participants.append(match.joiner)
    context = {
        'dispute': dispute,
        'match': match,
        'participants': participants,
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
            message=f"Dispute for match {match.get_game_display()} resolved. Winner: {winner.username}."
        )
        if match.joiner:
            Notification.objects.create(
                user=match.joiner,
                message=f"Dispute for match {match.get_game_display()} resolved. Winner: {winner.username}."
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