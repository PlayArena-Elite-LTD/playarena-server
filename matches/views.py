from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.http import HttpResponseNotAllowed, JsonResponse
from django.urls import reverse
from decimal import Decimal
from core.ratelimit import ratelimit

from .forms import MatchCreationForm, JoinMatchForm
from .models import Match, MatchResult
from .utils import get_result_query_info
from wallet.models import Wallet, Transaction
from alert.models import Notification


User = get_user_model()


def _get_rate_limit_key(group, request):
    """
    Get rate limit key: use user ID if authenticated, otherwise use IP.
    This ensures rate limiting works correctly even when @ratelimit is outermost.
    Returns just the identifier (user ID or IP) - django-ratelimit adds its own prefix.
    """
    if hasattr(request, 'user') and request.user.is_authenticated:
        return str(request.user.id)
    return request.META.get('REMOTE_ADDR', 'unknown')


@ratelimit(key=_get_rate_limit_key, rate='10/h', method='POST', block=True)
@login_required
@transaction.atomic
def create_match(request):
    """Create a new match and deduct the amount from user's wallet - 10 per hour per user"""
    if request.method == 'POST':
        form = MatchCreationForm(request.POST, user=request.user)
        if form.is_valid():
            match = form.save(commit=False)
            match.creator = request.user
            
            # Save the match first to get an ID
            match.save()
            
            # Deduct match amount from user's wallet
            wallet = request.user.wallet
            match_amount = form.cleaned_data['amount']
            
            wallet.balance -= Decimal(match_amount)
            wallet.save()
            
            # Now record the transaction with the saved match
            Transaction.objects.create(
                wallet=wallet,
                amount=-Decimal(match_amount),
                transaction_type='MATCH_CREATION',
                description=f"Created {match.get_game_display()} match for ZMW {match_amount}",
                related_match=match
            )
            
            messages.success(request, f"Match created successfully! Your match code is {match.joining_code}")
            return redirect('match_detail', match_id=match.id)
    else:
        form = MatchCreationForm(user=request.user)
    
    context = {
        'form': form,
        'username': request.user.username
    }
    
    return render(request, 'matches/create_match.html', context)

@ratelimit(key=_get_rate_limit_key, rate='20/h', method='POST', block=True)
@login_required
@transaction.atomic
def join_match(request):
    """Join an existing match using a code and deduct the amount from user's wallet"""
    if request.method == 'POST':
        joining_code = request.POST.get('joining_code', '').strip()
        if not joining_code:
            messages.error(request, "Please enter a valid joining code.")
            return redirect('available_matches')
        
        try:
            match = Match.objects.select_for_update().get(joining_code=joining_code, status='OPEN')
            
            # Check if user is trying to join their own match
            if match.creator == request.user:
                messages.error(request, "You cannot join your own match.")
                return redirect('available_matches')
            
            # Check if user has enough funds before mutating the match.
            try:
                wallet = Wallet.objects.select_for_update().get(user=request.user)
            except Wallet.DoesNotExist:
                messages.error(request, "Wallet not found. Please open your wallet and try again.")
                return redirect('available_matches')

            match_amount = Decimal(match.amount)
            if wallet.balance < match_amount:
                messages.error(
                    request,
                    f"Insufficient funds. Your balance is ZMW {wallet.balance:.2f}, "
                    f"but you need ZMW {match_amount:.2f} to join this match."
                )
                return redirect('available_matches')
            
            # Update match with joiner and change status first
            match.joiner = request.user
            match.status = 'JOINED'
            match.save()
            
            # Then deduct match amount from user's wallet
            wallet.balance -= match_amount
            wallet.save()
            
            # Record transaction
            Transaction.objects.create(
                wallet=wallet,
                amount=-match_amount,
                transaction_type='MATCH_JOINING',
                description=f"Joined {match.get_game_display()} match against {match.creator.username} for ZMW {match.amount}",
                related_match=match
            )
            
            # Create notification for the match creator
            Notification.objects.create(
                user=match.creator,
                message=f"{request.user.username} has joined your {match.get_game_display()} match for ZMW {match.amount}."
            )
            
            messages.success(request, f"You've successfully joined the {match.get_game_display()} match!")
            return redirect('match_detail', match_id=match.id)
            
        except Match.DoesNotExist:
            messages.error(request, "Invalid match code or the match is no longer available.")
            return redirect('available_matches')
    
    # If it's a GET request, redirect to available_matches
    return redirect('available_matches')


@login_required
@transaction.atomic
def cancel_match(request, match_id):
    """Cancel a match and handle refunds appropriately based on user role"""
    match = get_object_or_404(Match, id=match_id)
    
    # Check that the user is either the creator or joiner of the match
    if request.user != match.creator and request.user != match.joiner:
        messages.error(request, "You don't have permission to cancel this match.")
        return redirect('my_matches')
    
    # Verify the match is in a cancellable state
    if match.status not in ['OPEN', 'JOINED']:
        messages.error(request, f"Cannot cancel a match with status '{match.get_status_display()}'.")
        return redirect('match_detail', match_id=match.id)

    # Once either player has submitted a result, the match can no longer be
    # self-cancelled — this prevents a losing player from dodging the result
    # by cancelling instead of accepting it. From here it must be resolved
    # via result submission (agreement) or a dispute.
    result = MatchResult.objects.filter(match=match).first()
    if result and (result.creator_submission or result.joiner_submission):
        messages.error(request, "This match can't be cancelled because a result has already been submitted. Please submit your result or contact support.")
        return redirect('match_detail', match_id=match.id)

    # Store match information before potential deletion
    match_game = match.get_game_display()
    match_amount = match.amount
    
    # Handle cancellation differently based on whether user is creator or joiner
    if request.user == match.creator:
        # Creator is cancelling the match
        # Refund creator
        creator_wallet = match.creator.wallet
        creator_wallet.balance += Decimal(match.amount)
        creator_wallet.save()
        
        # Record transaction for creator refund
        Transaction.objects.create(
            wallet=creator_wallet,
            amount=Decimal(match.amount),
            transaction_type='MATCH_REFUND',
            description=f"Refund from cancelled {match_game} match for ZMW {match_amount}",
            related_match=match
        )
        
        # If there's a joiner, refund them too and notify
        if match.joiner:
            joiner = match.joiner  # Store joiner before deleting match
            joiner_wallet = joiner.wallet
            joiner_wallet.balance += Decimal(match.amount)
            joiner_wallet.save()
            
            # Record transaction for joiner refund
            Transaction.objects.create(
                wallet=joiner_wallet,
                amount=Decimal(match.amount),
                transaction_type='MATCH_REFUND',
                description=f"Refund from cancelled {match_game} match for ZMW {match_amount}",
                related_match=match
            )
            
            # Create notification for the joiner
            Notification.objects.create(
                user=joiner,
                message=f"A {match_game} match you joined has been cancelled by the creator. ZMW {match_amount} has been refunded to your wallet."
            )
        
        # Delete the match after all transactions are recorded
        match.delete()
        messages.success(request, f"Your {match_game} match has been cancelled and ZMW {match_amount} has been refunded to your wallet.")
        
    else:
        # Joiner is leaving the match
        joiner_wallet = match.joiner.wallet
        joiner_wallet.balance += Decimal(match.amount)
        joiner_wallet.save()
        
        # Update match state before creating transaction
        match.joiner = None
        match.status = 'OPEN'
        match.save()
        
        # Record transaction (after match is updated)
        Transaction.objects.create(
            wallet=joiner_wallet,
            amount=Decimal(match.amount),
            transaction_type='MATCH_REFUND',
            description=f"Refund from leaving {match_game} match for ZMW {match_amount}",
            related_match=match
        )
        
        # Create notification for the creator
        Notification.objects.create(
            user=match.creator,
            message=f"{request.user.username} has left your {match_game} match. The match is now open for others to join."
        )
        
        messages.success(request, f"You've left the match and ZMW {match.amount} has been refunded to your wallet.")
    
    return redirect('my_matches')

@ratelimit(key=_get_rate_limit_key, rate='20/h', method='POST', block=True)
@login_required
@transaction.atomic
def submit_match_result(request, match_id):
    """Submit match result (win, loss, or draw) and handle verification - 20 per hour per user"""
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    
    submission = request.POST.get('submission', '').upper()
    if submission not in ['WON', 'LOST', 'DRAW']:
        messages.error(request, "Invalid submission. Please select Won, Lost, or Draw.")
        return redirect('match_detail', match_id=match_id)
    
    # Get match and check if user is a participant
    match = get_object_or_404(Match, id=match_id)
    
    # Check if match is in the JOINED state
    if match.status != 'JOINED':
        messages.error(request, f"Cannot submit result for a match with status '{match.get_status_display()}'.")
        return redirect('match_detail', match_id=match_id)
    
    # Check if user is a participant
    if request.user != match.creator and request.user != match.joiner:
        messages.error(request, "You are not a participant in this match.")
        return redirect('my_matches')
    
    # Get or create match result
    match_result, created = MatchResult.objects.get_or_create(match=match)
    
    # Determine if user is creator or joiner and check if they've already submitted
    is_creator = (request.user == match.creator)
    
    # Lock check: Prevent resubmission if user has already submitted in current round
    if is_creator:
        # Check if creator has already submitted in the current round
        if match_result.creator_submission and match_result.creator_submission_time:
            # Additional check: if submission was made in round 2, it's locked
            if match_result.submission_round == 2:
                messages.error(request, "You have already submitted your result for this match. Results cannot be changed once submitted.")
                return redirect('match_detail', match_id=match_id)
            # For round 1, only allow resubmission if explicitly reset for round 2
            # But if submission_time exists, it means they've submitted and it's locked
            messages.error(request, "You have already submitted your result for this match. Results cannot be changed once submitted.")
            return redirect('match_detail', match_id=match_id)
        
        # Save creator's submission - LOCK IT
        match_result.creator_submission = submission
        match_result.creator_submission_time = timezone.now()
        match_result.save()
        
        # Check if joiner has submitted
        if not match_result.joiner_submission:
            # Notify joiner to submit their result
            submission_link = reverse('match_detail', args=[match.id])
            Notification.objects.create(
                user=match.joiner,
                message=f"Your opponent {match.creator.username} has submitted their result for the {match.get_game_display()} match (ZMW {match.amount}). Please submit your result as soon as possible.",
                link=submission_link,
            )
            messages.success(request, "Your result has been submitted. Waiting for your opponent to submit their result.")
            return redirect('match_detail', match_id=match_id)
    else:  # User is joiner
        # Check if joiner has already submitted in the current round
        if match_result.joiner_submission and match_result.joiner_submission_time:
            # Additional check: if submission was made in round 2, it's locked
            if match_result.submission_round == 2:
                messages.error(request, "You have already submitted your result for this match. Results cannot be changed once submitted.")
                return redirect('match_detail', match_id=match_id)
            # For round 1, only allow resubmission if explicitly reset for round 2
            # But if submission_time exists, it means they've submitted and it's locked
            messages.error(request, "You have already submitted your result for this match. Results cannot be changed once submitted.")
            return redirect('match_detail', match_id=match_id)
        
        # Save joiner's submission - LOCK IT
        match_result.joiner_submission = submission
        match_result.joiner_submission_time = timezone.now()
        match_result.save()
        
        # Check if creator has submitted
        if not match_result.creator_submission:
            # Notify creator to submit their result
            submission_link = reverse('match_detail', args=[match.id])
            Notification.objects.create(
                user=match.creator,
                message=f"Your opponent {match.joiner.username} has submitted their result for the {match.get_game_display()} match (ZMW {match.amount}). Please submit your result as soon as possible.",
                link=submission_link,
            )
            messages.success(request, "Your result has been submitted. Waiting for your opponent to submit their result.")
            return redirect('match_detail', match_id=match_id)
    
    # If we reach here, both users have submitted
    # Check if submissions are consistent
    creator_sub = match_result.creator_submission
    joiner_sub = match_result.joiner_submission
    
    # Consistent submissions
    if (creator_sub == 'WON' and joiner_sub == 'LOST') or \
       (creator_sub == 'LOST' and joiner_sub == 'WON') or \
       (creator_sub == 'DRAW' and joiner_sub == 'DRAW'):
        
        # Handle results
        if creator_sub == 'WON':
            winner = match.creator
            loser = match.joiner
        elif joiner_sub == 'WON':
            winner = match.joiner
            loser = match.creator
        else:  # Draw
            from .settlement import settle_match
            match = settle_match(match, draw=True)
            refund_amount = Decimal(match.amount) * Decimal('0.9')
            # Notify both users
            Notification.objects.create(
                user=match.creator,
                message=f"Your {match.get_game_display()} match against {match.joiner.username} for ZMW {match.amount} ended in a draw. ZMW {refund_amount} has been returned to your wallet."
            )
            
            Notification.objects.create(
                user=match.joiner,
                message=f"Your {match.get_game_display()} match against {match.creator.username} for ZMW {match.amount} ended in a draw. ZMW {refund_amount} has been returned to your wallet."
            )

            messages.success(request, f"Match result recorded as a draw. ZMW {refund_amount} has been returned to your wallet.")
            return redirect('match_detail', match_id=match_id)
        
        from .settlement import settle_match
        match = settle_match(match, winner=winner)
        
        # Notify both users
        Notification.objects.create(
            user=winner,
            message=f"Congratulations! You won the {match.get_game_display()} match against {loser.username} for ZMW {match.amount}. ZMW {match.winnings} has been added to your wallet."
        )
        
        Notification.objects.create(
            user=loser,
            message=f"You lost the {match.get_game_display()} match against {winner.username} for ZMW {match.amount}."
        )
        
        messages.success(request, "Match result recorded successfully.")
        return redirect('match_detail', match_id=match_id)
    
    # Inconsistent submissions
    else:
        if match_result.submission_round == 1:
            # Reset submissions for round 2 - but mark that round 1 submissions were locked
            # Only reset if both users submitted (which they have at this point)
            # This allows one more chance, but once submitted in round 2, it's permanently locked
            match_result.creator_submission = None
            match_result.creator_submission_time = None
            match_result.joiner_submission = None
            match_result.joiner_submission_time = None
            match_result.submission_round = 2
            match_result.save()
            
            # Notify both users
            submission_link = reverse('match_detail', args=[match.id])
            Notification.objects.create(
                user=match.creator,
                message=f"There was a disagreement in the result for your {match.get_game_display()} match against {match.joiner.username} for ZMW {match.amount}. You have one more chance to submit the correct result.",
                link=submission_link,
            )
            
            Notification.objects.create(
                user=match.joiner,
                message=f"There was a disagreement in the result for your {match.get_game_display()} match against {match.creator.username} for ZMW {match.amount}. You have one more chance to submit the correct result.",
                link=submission_link,
            )
            
            messages.warning(request, "There was a disagreement with the match results. Both players must submit again with accurate results.")
            return redirect('match_detail', match_id=match_id)
            
        else:  # Round 2 with conflict
            # Mark the match as disputed
            match.status = 'DISPUTED'
            match.save()
            
            # Add to disputes (this would be implemented in the panel app later)
            try:
                # Assuming the Dispute model exists in the panel app
                from panel.models import Dispute
                Dispute.objects.create(
                    match=match,
                    status='OPEN'
                )
            except ImportError:
                # If the model doesn't exist yet, just log it
                print(f"Match {match_id} has been marked as disputed and requires admin intervention.")
            
            # Notify both users
            Notification.objects.create(
                user=match.creator,
                message=f"Your {match.get_game_display()} match against {match.joiner.username} for ZMW {match.amount} has been marked as disputed and will be reviewed by support."
            )
            
            Notification.objects.create(
                user=match.joiner,
                message=f"Your {match.get_game_display()} match against {match.creator.username} for ZMW {match.amount} has been marked as disputed and will be reviewed by support."
            )
            
            messages.error(request, "Match has been marked as disputed due to conflicting results and will be reviewed by support.")
            return redirect('match_detail', match_id=match_id)


@ratelimit(key=_get_rate_limit_key, rate='5/h', method='POST', block=True)
@login_required
@transaction.atomic
def query_unanswered_result(request, match_id):
    """Send a stale one-sided result submission to support for resolution."""
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    match = get_object_or_404(
        Match.objects.select_for_update().select_related('creator', 'joiner'),
        id=match_id,
    )

    if request.user != match.creator and request.user != match.joiner:
        messages.error(request, "You are not a participant in this match.")
        return redirect('my_matches')

    match_result = MatchResult.objects.select_for_update().filter(match=match).first()
    query_info = get_result_query_info(match, match_result, request.user)
    if not query_info['can_query']:
        if query_info['available_at']:
            messages.error(
                request,
                "You can query support if your opponent has not submitted after 24 hours."
            )
        else:
            messages.error(request, "This match is not eligible for a result query.")
        return redirect('match_detail', match_id=match_id)

    from panel.models import Dispute

    dispute, created = Dispute.objects.get_or_create(
        match=match,
        defaults={
            'status': 'OPEN',
            'resolution_notes': (
                f"Result query opened by {request.user.username}. "
                f"Opponent did not submit within 24 hours."
            ),
        },
    )

    if not created and dispute.status == 'RESOLVED':
        messages.error(request, "This dispute has already been resolved.")
        return redirect('match_detail', match_id=match_id)

    match.status = 'DISPUTED'
    match.save(update_fields=['status'])

    opponent = match.joiner if request.user == match.creator else match.creator
    Notification.objects.create(
        user=request.user,
        message=(
            f"Your {match.get_game_display()} match result query has been sent to support. "
            "An admin will review and award the winner."
        ),
        link=reverse('match_detail', args=[match.id]),
    )
    Notification.objects.create(
        user=opponent,
        message=(
            f"{request.user.username} has sent the {match.get_game_display()} match to support "
            "because your result was not submitted within 24 hours."
        ),
        link=reverse('match_detail', args=[match.id]),
    )

    dispute_link = reverse('dispute_detail', args=[dispute.id])
    support_users = User.objects.filter(is_active=True).filter(
        Q(is_support_staff=True) | Q(is_staff=True) | Q(is_superuser=True)
    ).distinct()
    for support_user in support_users:
        Notification.objects.create(
            user=support_user,
            message=(
                f"Result query opened for {match.get_game_display()} match "
                f"{match.joining_code}. Review and award the winner."
            ),
            link=dispute_link,
        )

    messages.success(request, "Your query has been sent to support for admin review.")
    return redirect('match_detail', match_id=match_id)


@login_required
def match_detail(request, match_id):
    """Display match details"""
    try:
        match = Match.objects.get(id=match_id)
        
        # Check if user is allowed to view this match
        if match.privacy == 'PRIVATE' and request.user != match.creator and request.user != match.joiner:
            messages.error(request, "You don't have permission to view this match.")
            return redirect('dashboard')
        
        # Get match result to check submission status
        try:
            match_result = MatchResult.objects.get(match=match)
            # Check if current user has already submitted
            is_creator = (request.user == match.creator)
            if is_creator:
                user_has_submitted = bool(match_result.creator_submission and match_result.creator_submission_time)
                user_submission = match_result.creator_submission
            else:
                user_has_submitted = bool(match_result.joiner_submission and match_result.joiner_submission_time)
                user_submission = match_result.joiner_submission
        except MatchResult.DoesNotExist:
            match_result = None
            user_has_submitted = False
            user_submission = None

        result_query_info = get_result_query_info(match, match_result, request.user)
        
        context = {
            'match': match,
            'match_result': match_result,
            'user_has_submitted': user_has_submitted,
            'user_submission': user_submission,
            'result_query_info': result_query_info,
            'username': request.user.username
        }
        
        return render(request, 'matches/match_detail.html', context)
        
    except Match.DoesNotExist:
        messages.error(request, "The requested match is not available.")
        return redirect('my_matches')

@login_required
def my_matches(request):
    """Display a list of user's matches"""
    created_matches = Match.objects.filter(creator=request.user).order_by('-created_at')
    joined_matches = Match.objects.filter(joiner=request.user).order_by('-created_at')
    
    context = {
        'created_matches': created_matches,
        'joined_matches': joined_matches,
        'username': request.user.username
    }
    
    return render(request, 'matches/my_matches.html', context)

@login_required
def available_matches(request):
    """Display a list of available public matches"""
    matches = Match.objects.filter(
        privacy='PUBLIC',
        status='OPEN'
    ).exclude(creator=request.user).order_by('-created_at')
    
    context = {
        'matches': matches,
        'username': request.user.username
    }
    
    return render(request, 'matches/available_matches.html', context)

@ratelimit(key=_get_rate_limit_key, rate='20/h', method='POST', block=True)
@login_required
def upload_evidence(request, match_id):
    """Upload evidence for a match"""
    match = get_object_or_404(Match, id=match_id)
    
    # Check if user is part of this match
    if match.creator != request.user and match.opponent != request.user:
        messages.error(request, "You are not part of this match")
        return redirect('match_detail', match_id=match_id)
    
    if request.method == 'POST':
        # Handle file upload logic here
        messages.success(request, "Evidence uploaded successfully")
        return redirect('match_detail', match_id=match_id)
    
    return render(request, 'matches/upload_evidence.html', {'match': match})

@login_required
def evidence_gallery(request, match_id):
    """Display evidence gallery for a match"""
    match = get_object_or_404(Match, id=match_id)
    
    # Check if user is part of this match
    if match.creator != request.user and match.opponent != request.user:
        messages.error(request, "You are not part of this match")
        return redirect('match_detail', match_id=match_id)
    
    return render(request, 'matches/evidence_gallery.html', {'match': match})

@login_required
def get_evidence(request, evidence_id):
    """Get evidence details"""
    # Placeholder implementation
    return JsonResponse({'status': 'success', 'evidence_id': evidence_id})

@login_required
def download_evidence(request, evidence_id):
    """Download evidence file"""
    # Placeholder implementation
    return JsonResponse({'status': 'success', 'action': 'download', 'evidence_id': evidence_id})

@login_required
def delete_evidence(request, evidence_id):
    """Delete evidence"""
    # Placeholder implementation
    return JsonResponse({'status': 'success', 'action': 'delete', 'evidence_id': evidence_id})

@login_required
def list_evidence(request, match_id):
    """List all evidence for a match"""
    match = get_object_or_404(Match, id=match_id)
    
    # Check if user is part of this match
    if match.creator != request.user and match.opponent != request.user:
        return JsonResponse({'error': 'Not authorized'}, status=403)
    
    # Placeholder implementation
    return JsonResponse({'status': 'success', 'match_id': match_id, 'evidence': []})
