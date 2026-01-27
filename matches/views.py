from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.utils import timezone
from django.http import HttpResponseNotAllowed, JsonResponse, FileResponse, Http404
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from decimal import Decimal
from django_ratelimit.decorators import ratelimit
import logging
import os

from .forms import MatchCreationForm, JoinMatchForm, EvidenceUploadForm
from .models import Match, MatchResult, Evidence
from wallet.models import Wallet, Transaction
from alert.models import Notification

logger = logging.getLogger('django_ratelimit')


def _get_client_ip(request):
    """Get client IP address from request"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip

# Alias for backward compatibility
get_client_ip = _get_client_ip

@login_required
@transaction.atomic
@ratelimit(key='user', rate='10/h', method='POST', block=True)
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
                description=f"Created {match.get_game_display()} match for ${match_amount}",
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
            match = Match.objects.get(joining_code=joining_code, status='OPEN')
            
            # Check if user is trying to join their own match
            if match.creator == request.user:
                messages.error(request, "You cannot join your own match.")
                return redirect('available_matches')
            
            # Check if user has enough funds
            wallet = request.user.wallet
            if wallet.balance < Decimal(match.amount):
                messages.error(request, f"Insufficient funds. You need ${match.amount} to join this match.")
                return redirect('available_matches')
            
            # Update match with joiner and change status first
            match.joiner = request.user
            match.status = 'JOINED'
            match.save()
            
            # Then deduct match amount from user's wallet
            wallet.balance -= Decimal(match.amount)
            wallet.save()
            
            # Record transaction
            Transaction.objects.create(
                wallet=wallet,
                amount=-Decimal(match.amount),
                transaction_type='MATCH_JOINING',
                description=f"Joined {match.get_game_display()} match against {match.creator.username} for ${match.amount}",
                related_match=match
            )
            
            # Create notification for the match creator
            Notification.objects.create(
                user=match.creator,
                message=f"{request.user.username} has joined your {match.get_game_display()} match for ${match.amount}."
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
            description=f"Refund from cancelled {match_game} match for ${match_amount}",
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
                description=f"Refund from cancelled {match_game} match for ${match_amount}",
                related_match=match
            )
            
            # Create notification for the joiner
            Notification.objects.create(
                user=joiner,
                message=f"A {match_game} match you joined has been cancelled by the creator. ${match_amount} has been refunded to your wallet."
            )
        
        # Delete the match after all transactions are recorded
        match.delete()
        messages.success(request, f"Your {match_game} match has been cancelled and ${match_amount} has been refunded to your wallet.")
        
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
            description=f"Refund from leaving {match_game} match for ${match_amount}",
            related_match=match
        )
        
        # Create notification for the creator
        Notification.objects.create(
            user=match.creator,
            message=f"{request.user.username} has left your {match_game} match. The match is now open for others to join."
        )
        
        messages.success(request, f"You've left the match and ${match.amount} has been refunded to your wallet.")
    
    return redirect('my_matches')

@login_required
@transaction.atomic
@ratelimit(key='user', rate='20/h', method='POST', block=True)
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
    
    # Handle evidence upload if provided (optional)
    evidence_uploaded = False
    if 'evidence_file' in request.FILES:
        evidence_form = EvidenceUploadForm(request.POST, request.FILES)
        if evidence_form.is_valid():
            try:
                evidence_file = evidence_form.cleaned_data['evidence_file']
                description = evidence_form.cleaned_data.get('description', '').strip()
                file_type = evidence_form.get_file_type()
                
                # Create Evidence instance
                Evidence.objects.create(
                    match=match,
                    user=request.user,
                    file=evidence_file,
                    file_type=file_type,
                    description=description if description else None
                )
                evidence_uploaded = True
            except Exception as e:
                logger.error(f"Error uploading evidence for match {match_id} by user {request.user.id}: {str(e)}")
                # Don't fail the result submission if evidence upload fails
                messages.warning(request, "Your result was submitted, but there was an error uploading evidence. You can upload evidence separately if needed.")
        else:
            # Evidence validation failed, but don't block result submission
            messages.warning(request, "Your result was submitted, but the evidence file could not be processed. You can upload evidence separately if needed.")
    
    # Determine if user is creator or joiner and check if they've already submitted
    is_creator = (request.user == match.creator)
    
    if is_creator:
        if match_result.creator_submission:
            messages.error(request, "You have already submitted your result for this match.")
            return redirect('match_detail', match_id=match_id)
        
        # Save creator's submission
        match_result.creator_submission = submission
        match_result.creator_submission_time = timezone.now()
        match_result.save()
        
        # Check if joiner has submitted
        if not match_result.joiner_submission:
            # Notify joiner to submit their result
            Notification.objects.create(
                user=match.joiner,
                message=f"Your opponent {match.creator.username} has submitted their result for the {match.get_game_display()} match (${match.amount}). Please submit your result as soon as possible."
            )
            success_msg = "Your result has been submitted. Waiting for your opponent to submit their result."
            if evidence_uploaded:
                success_msg += " Evidence has been uploaded."
            messages.success(request, success_msg)
            return redirect('match_detail', match_id=match_id)
    else:  # User is joiner
        if match_result.joiner_submission:
            messages.error(request, "You have already submitted your result for this match.")
            return redirect('match_detail', match_id=match_id)
        
        # Save joiner's submission
        match_result.joiner_submission = submission
        match_result.joiner_submission_time = timezone.now()
        match_result.save()
        
        # Check if creator has submitted
        if not match_result.creator_submission:
            # Notify creator to submit their result
            Notification.objects.create(
                user=match.creator,
                message=f"Your opponent {match.joiner.username} has submitted their result for the {match.get_game_display()} match (${match.amount}). Please submit your result as soon as possible."
            )
            success_msg = "Your result has been submitted. Waiting for your opponent to submit their result."
            if evidence_uploaded:
                success_msg += " Evidence has been uploaded."
            messages.success(request, success_msg)
            return redirect('match_detail', match_id=match_id)
    
    # If we reach here, both users have submitted
    # Check if submissions are consistent
    creator_sub = match_result.creator_submission
    joiner_sub = match_result.joiner_submission
    
    # Consistent submissions
    if (creator_sub == 'WON' and joiner_sub == 'LOST') or \
       (creator_sub == 'LOST' and joiner_sub == 'WON') or \
       (creator_sub == 'DRAW' and joiner_sub == 'DRAW'):
        
        # Update match status first
        match.status = 'COMPLETED'
        match.save()
        
        # Handle results
        if creator_sub == 'WON':
            winner = match.creator
            loser = match.joiner
        elif joiner_sub == 'WON':
            winner = match.joiner
            loser = match.creator
        else:  # Draw
            # Return 90% of match amount to each user
            creator_wallet = match.creator.wallet
            joiner_wallet = match.joiner.wallet
            
            refund_amount = Decimal(match.amount) * Decimal('0.9')
            
            # Update wallets first
            creator_wallet.balance += refund_amount
            creator_wallet.save()
            
            joiner_wallet.balance += refund_amount
            joiner_wallet.save()
            
            # Then record transactions
            Transaction.objects.create(
                wallet=creator_wallet,
                amount=refund_amount,
                transaction_type='MATCH_DRAW_RETURN',
                description=f"Return from draw in {match.get_game_display()} match against {match.joiner.username} for ${match.amount}",
                related_match=match
            )
            
            Transaction.objects.create(
                wallet=joiner_wallet,
                amount=refund_amount,
                transaction_type='MATCH_DRAW_RETURN',
                description=f"Return from draw in {match.get_game_display()} match against {match.creator.username} for ${match.amount}",
                related_match=match
            )
            
            # Notify both users
            Notification.objects.create(
                user=match.creator,
                message=f"Your {match.get_game_display()} match against {match.joiner.username} for ${match.amount} ended in a draw. ${refund_amount} has been returned to your wallet."
            )
            
            Notification.objects.create(
                user=match.joiner,
                message=f"Your {match.get_game_display()} match against {match.creator.username} for ${match.amount} ended in a draw. ${refund_amount} has been returned to your wallet."
            )
            
            messages.success(request, f"Match result recorded as a draw. ${refund_amount} has been returned to your wallet.")
            return redirect('match_detail', match_id=match_id)
        
        # Handle winner gets winnings - update wallet first
        winner_wallet = winner.wallet
        winner_wallet.balance += Decimal(match.winnings)
        winner_wallet.save()
        
        # Then record transaction
        Transaction.objects.create(
            wallet=winner_wallet,
            amount=Decimal(match.winnings),
            transaction_type='MATCH_WINNINGS',
            description=f"Winnings from {match.get_game_display()} match against {loser.username} for ${match.amount}",
            related_match=match
        )
        
        # Notify both users
        Notification.objects.create(
            user=winner,
            message=f"Congratulations! You won the {match.get_game_display()} match against {loser.username} for ${match.amount}. ${match.winnings} has been added to your wallet."
        )
        
        Notification.objects.create(
            user=loser,
            message=f"You lost the {match.get_game_display()} match against {winner.username} for ${match.amount}."
        )
        
        messages.success(request, "Match result recorded successfully.")
        return redirect('match_detail', match_id=match_id)
    
    # Inconsistent submissions
    else:
        if match_result.submission_round == 1:
            # Reset submissions for round 2
            match_result.creator_submission = None
            match_result.creator_submission_time = None
            match_result.joiner_submission = None
            match_result.joiner_submission_time = None
            match_result.submission_round = 2
            match_result.save()
            
            # Notify both users
            Notification.objects.create(
                user=match.creator,
                message=f"There was a disagreement in the result for your {match.get_game_display()} match against {match.joiner.username} for ${match.amount}. You have one more chance to submit the correct result."
            )
            
            Notification.objects.create(
                user=match.joiner,
                message=f"There was a disagreement in the result for your {match.get_game_display()} match against {match.creator.username} for ${match.amount}. You have one more chance to submit the correct result."
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
                message=f"Your {match.get_game_display()} match against {match.joiner.username} for ${match.amount} has been marked as disputed and will be reviewed by support."
            )
            
            Notification.objects.create(
                user=match.joiner,
                message=f"Your {match.get_game_display()} match against {match.creator.username} for ${match.amount} has been marked as disputed and will be reviewed by support."
            )
            
            messages.error(request, "Match has been marked as disputed due to conflicting results and will be reviewed by support.")
            return redirect('match_detail', match_id=match_id)


@login_required
@transaction.atomic
@ratelimit(key='user', rate='10/h', method='POST', block=True)
def upload_evidence(request, match_id):
    """
    Handle evidence file uploads for match results.
    
    Security features:
    - Rate limiting (10 uploads per hour per user)
    - IP address tracking
    - User agent tracking
    - File type and size validation
    - Access control (only match participants can upload)
    
    POST: Upload evidence file
    Returns: JSON response with upload result
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Only POST method allowed'}, status=405)
    
    # Get match and verify user is a participant
    match = get_object_or_404(Match, id=match_id)
    
    # Security: Only match participants can upload evidence
    if request.user != match.creator and request.user != match.joiner:
        return JsonResponse({
            'success': False,
            'error': 'You are not a participant in this match.'
        }, status=403)
    
    # Security: Only allow uploads for matches in JOINED or COMPLETED status
    if match.status not in ['JOINED', 'COMPLETED', 'DISPUTED']:
        return JsonResponse({
            'success': False,
            'error': f'Cannot upload evidence for a match with status: {match.get_status_display()}'
        }, status=400)
    
    # Create form with match and user context
    form = EvidenceUploadForm(request.POST, request.FILES, match=match, user=request.user)
    
    if form.is_valid():
        try:
            file = form.cleaned_data['file']
            file_type = form.cleaned_data['file_type']
            description = form.cleaned_data.get('description', '')
            
            # Security: Capture IP address and user agent
            ip_address = _get_client_ip(request)
            user_agent = request.META.get('HTTP_USER_AGENT', '')[:500]  # Limit length
            
            # Create Evidence instance
            evidence = Evidence(
                match=match,
                user=request.user,
                file=file,
                file_type=file_type,
                description=description,
                file_size=file.size,
                ip_address=ip_address,
                user_agent=user_agent
            )
            
            # Save (validation and hash generation happen in save method)
            try:
                evidence.save()
            except ValidationError as ve:
                # Handle model validation errors
                errors = {}
                if hasattr(ve, 'error_dict'):
                    for field, field_errors in ve.error_dict.items():
                        errors[field] = [str(err) for err in field_errors]
                else:
                    errors['__all__'] = [str(ve)]
                
                return JsonResponse({
                    'success': False,
                    'errors': errors
                }, status=400)
            
            logger.info(
                f"Evidence uploaded successfully: match_id={match_id}, "
                f"user={request.user.username}, file_type={file_type}, "
                f"file_size={file.size}"
            )
            
            return JsonResponse({
                'success': True,
                'evidence_id': evidence.id,
                'file_url': evidence.file.url,
                'file_type': file_type,
                'file_size_mb': evidence.file_size_mb,
                'message': 'Evidence uploaded successfully'
            })
            
        except Exception as e:
            logger.error(
                f"Error uploading evidence for match {match_id}: {str(e)}",
                exc_info=True
            )
            return JsonResponse({
                'success': False,
                'error': f'Error uploading evidence: {str(e)}'
            }, status=500)
    else:
        # Return form errors
        errors = {}
        for field, field_errors in form.errors.items():
            errors[field] = field_errors[0] if field_errors else 'Invalid value'
        
        return JsonResponse({
            'success': False,
            'errors': errors
        }, status=400)


@login_required
def match_detail(request, match_id):
    """Display match details"""
    try:
        match = Match.objects.get(id=match_id)
        
        # Check if user is allowed to view this match
        if match.privacy == 'PRIVATE' and request.user != match.creator and request.user != match.joiner:
            messages.error(request, "You don't have permission to view this match.")
            return redirect('dashboard')
        
        # Get all evidence for this match
        evidence_list = Evidence.objects.filter(match=match).order_by('-uploaded_at')
        
        context = {
            'match': match,
            'username': request.user.username,
            'evidence_list': evidence_list,
        }
        
        return render(request, 'matches/match_detail.html', context)
        
    except Match.DoesNotExist:
        messages.error(request, "The requested match is not available.")
        return redirect('my_matches')


@login_required
def evidence_gallery(request, match_id):
    """Display evidence gallery for a match"""
    try:
        match = Match.objects.get(id=match_id)
        
        # Check if user is allowed to view this match
        if match.privacy == 'PRIVATE' and request.user != match.creator and request.user != match.joiner:
            messages.error(request, "You don't have permission to view this match.")
            return redirect('dashboard')
        
        # Get all evidence for this match
        evidence_list = Evidence.objects.filter(match=match).order_by('-uploaded_at')
        
        # Separate images and videos for better organization
        images = [e for e in evidence_list if e.file_type == 'IMAGE']
        videos = [e for e in evidence_list if e.file_type == 'VIDEO']
        
        context = {
            'match': match,
            'username': request.user.username,
            'evidence_list': evidence_list,
            'images': images,
            'videos': videos,
            'total_count': evidence_list.count(),
        }
        
        return render(request, 'matches/evidence_gallery.html', context)
        
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


@ratelimit(key='user', rate='30/h', method='GET', block=True)
def get_evidence(request, evidence_id):
    """
    Retrieve evidence file with access control.
    
    Security features:
    - Only match participants or support staff can view evidence
    - Rate limiting (30 requests/hour per user)
    - Access logging
    - Proper file serving with security headers
    
    GET: Retrieve evidence file
    Returns: FileResponse with evidence file
    """
    evidence = get_object_or_404(Evidence, id=evidence_id)
    match = evidence.match
    
    # Security: Check if user has permission to view evidence
    is_participant = (request.user == match.creator or request.user == match.joiner)
    is_support_staff = getattr(request.user, 'is_support_staff', False)
    
    if not (is_participant or is_support_staff):
        logger.warning(
            f"Unauthorized evidence access attempt: evidence_id={evidence_id}, "
            f"user={request.user.username}, ip={_get_client_ip(request)}"
        )
        return JsonResponse({
            'success': False,
            'error': 'You do not have permission to view this evidence.'
        }, status=403)
    
    # Security: Check if file exists
    if not evidence.file or not os.path.exists(evidence.file.path):
        logger.error(f"Evidence file not found: evidence_id={evidence_id}, path={evidence.file.path if evidence.file else 'None'}")
        raise Http404("Evidence file not found")
    
    # Log access
    logger.info(
        f"Evidence accessed: evidence_id={evidence_id}, user={request.user.username}, "
        f"match_id={match.id}, ip={_get_client_ip(request)}"
    )
    
    # Serve file with appropriate headers
    response = FileResponse(
        evidence.file.open('rb'),
        content_type=f"{'image' if evidence.is_image else 'video'}/{evidence.file.name.split('.')[-1]}"
    )
    
    # Security: Set appropriate headers
    response['Content-Disposition'] = f'inline; filename="{os.path.basename(evidence.file.name)}"'
    response['X-Content-Type-Options'] = 'nosniff'
    response['Cache-Control'] = 'private, max-age=3600'  # Cache for 1 hour
    
    return response


@login_required
@ratelimit(key='user', rate='30/h', method='GET', block=True)
def download_evidence(request, evidence_id):
    """
    Download evidence file with access control.
    
    Security features:
    - Only match participants or support staff can download evidence
    - Rate limiting (30 requests/hour per user)
    - Access logging
    - Force download with appropriate headers
    
    GET: Download evidence file
    Returns: FileResponse with evidence file (download)
    """
    evidence = get_object_or_404(Evidence, id=evidence_id)
    match = evidence.match
    
    # Security: Check if user has permission to download evidence
    is_participant = (request.user == match.creator or request.user == match.joiner)
    is_support_staff = getattr(request.user, 'is_support_staff', False)
    
    if not (is_participant or is_support_staff):
        logger.warning(
            f"Unauthorized evidence download attempt: evidence_id={evidence_id}, "
            f"user={request.user.username}, ip={_get_client_ip(request)}"
        )
        return JsonResponse({
            'success': False,
            'error': 'You do not have permission to download this evidence.'
        }, status=403)
    
    # Security: Check if file exists
    if not evidence.file or not os.path.exists(evidence.file.path):
        logger.error(f"Evidence file not found: evidence_id={evidence_id}, path={evidence.file.path if evidence.file else 'None'}")
        raise Http404("Evidence file not found")
    
    # Log access
    logger.info(
        f"Evidence downloaded: evidence_id={evidence_id}, user={request.user.username}, "
        f"match_id={match.id}, ip={_get_client_ip(request)}"
    )
    
    # Serve file with download headers
    response = FileResponse(
        evidence.file.open('rb'),
        content_type='application/octet-stream'
    )
    
    # Security: Force download
    filename = os.path.basename(evidence.file.name)
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    response['X-Content-Type-Options'] = 'nosniff'
    
    return response


@login_required
@ratelimit(key='user', rate='60/h', method='GET', block=True)
def list_evidence(request, match_id):
    """
    List all evidence for a match with access control.
    
    Security features:
    - Only match participants or support staff can list evidence
    - Rate limiting (60 requests/hour per user)
    - Pagination support
    - Optional filtering by user
    
    GET Parameters:
    - user_id (optional): Filter evidence by user
    - page (optional): Page number for pagination
    - per_page (optional): Items per page (default: 20, max: 100)
    
    Returns: JSON response with evidence list
    """
    match = get_object_or_404(Match, id=match_id)
    
    # Security: Check if user has permission to list evidence
    is_participant = (request.user == match.creator or request.user == match.joiner)
    is_support_staff = getattr(request.user, 'is_support_staff', False)
    
    if not (is_participant or is_support_staff):
        logger.warning(
            f"Unauthorized evidence list attempt: match_id={match_id}, "
            f"user={request.user.username}, ip={_get_client_ip(request)}"
        )
        return JsonResponse({
            'success': False,
            'error': 'You do not have permission to view evidence for this match.'
        }, status=403)
    
    # Get evidence queryset
    evidence_queryset = Evidence.objects.filter(match=match).select_related('user', 'verified_by')
    
    # Optional: Filter by user
    user_id = request.GET.get('user_id')
    if user_id:
        try:
            evidence_queryset = evidence_queryset.filter(user_id=user_id)
        except ValueError:
            return JsonResponse({
                'success': False,
                'error': 'Invalid user_id parameter.'
            }, status=400)
    
    # Pagination
    per_page = min(int(request.GET.get('per_page', 20)), 100)  # Max 100 per page
    page_number = request.GET.get('page', 1)
    
    paginator = Paginator(evidence_queryset, per_page)
    try:
        page = paginator.page(page_number)
    except Exception:
        return JsonResponse({
            'success': False,
            'error': 'Invalid page number.'
        }, status=400)
    
    # Serialize evidence data
    evidence_list = []
    for evidence in page.object_list:
        evidence_list.append({
            'id': evidence.id,
            'user': {
                'id': evidence.user.id,
                'username': evidence.user.username
            },
            'file_type': evidence.file_type,
            'file_url': evidence.file.url if evidence.file else None,
            'file_size': evidence.file_size,
            'file_size_mb': round(evidence.file_size_mb, 2) if evidence.file_size else 0,
            'description': evidence.description,
            'uploaded_at': evidence.uploaded_at.isoformat(),
            'is_verified': evidence.is_verified,
            'verified_by': {
                'id': evidence.verified_by.id,
                'username': evidence.verified_by.username
            } if evidence.verified_by else None,
            'verified_at': evidence.verified_at.isoformat() if evidence.verified_at else None,
        })
    
    # Log access
    logger.info(
        f"Evidence list accessed: match_id={match_id}, user={request.user.username}, "
        f"count={len(evidence_list)}, ip={_get_client_ip(request)}"
    )
    
    return JsonResponse({
        'success': True,
        'match_id': match_id,
        'evidence': evidence_list,
        'pagination': {
            'page': page.number,
            'per_page': per_page,
            'total_pages': paginator.num_pages,
            'total_count': paginator.count,
            'has_next': page.has_next(),
            'has_previous': page.has_previous(),
        }
    })


@login_required
@transaction.atomic
def delete_evidence(request, evidence_id):
    """
    Allow a user to delete their own evidence while the match is still active
    (JOINED or DISPUTED). This supports Day 9: evidence deletion before/around
    result submission.
    """
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    evidence = get_object_or_404(Evidence, id=evidence_id)
    match = evidence.match

    # Only the uploader can delete their own evidence
    if request.user != evidence.user:
        messages.error(request, "You don't have permission to delete this evidence.")
        return redirect('match_detail', match_id=match.id)

    # Only allow deletion while match is still under review/play
    if match.status not in ['JOINED', 'DISPUTED']:
        messages.error(
            request,
            f"Cannot delete evidence for a match with status '{match.get_status_display()}'."
        )
        return redirect('match_detail', match_id=match.id)

    evidence.delete()
    messages.success(request, "Evidence deleted successfully.")
    return redirect('match_detail', match_id=match.id)
