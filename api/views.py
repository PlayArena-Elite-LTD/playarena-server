from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.exceptions import PermissionDenied
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from decimal import Decimal
from .serializers import (
    UserSerializer,
    PublicUserSerializer,
    UserUpdateSerializer,
    ProfileSerializer,
    MatchSerializer,
    MatchCreateSerializer,
    MatchJoinSerializer,
    MatchResultSubmissionSerializer,
    UserRegistrationSerializer,
    ChangePasswordSerializer,
    WalletSerializer,
    TransactionSerializer,
    DepositCreateSerializer,
    WithdrawalCreateSerializer
)
from .permissions import IsWalletOwner
from accounts.models import CustomUser, Profile
from matches.models import Match, MatchResult
from alert.models import Notification
from wallet.models import Wallet, Transaction
from wallet.notifications import notify_withdrawal_created

User = get_user_model()


class UserRegistrationView(APIView):
    """
    POST /api/auth/register/
    
    Register a new user and return JWT tokens.
    
    Request body:
    {
        "username": "newuser",
        "email": "user@example.com",
        "password": "securepassword123",
        "password_confirm": "securepassword123"
    }
    
    Response:
    {
        "user": {
            "id": 1,
            "username": "newuser",
            "email": "user@example.com"
        },
        "access": "eyJ0eXAiOiJKV1QiLCJhbGc...",
        "refresh": "eyJ0eXAiOiJKV1QiLCJhbGc..."
    }
    """
    permission_classes = [permissions.AllowAny]
    
    def post(self, request):
        serializer = UserRegistrationSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            
            # Generate JWT tokens
            refresh = RefreshToken.for_user(user)
            
            # Return user data and tokens
            user_serializer = UserSerializer(user)
            return Response({
                'user': user_serializer.data,
                'access': str(refresh.access_token),
                'refresh': str(refresh)
            }, status=status.HTTP_201_CREATED)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ChangePasswordView(APIView):
    """
    POST /api/auth/change-password/
    
    Change user password. Requires authentication.
    
    Request body:
    {
        "old_password": "oldpass123",
        "new_password": "newpass123",
        "new_password_confirm": "newpass123"
    }
    
    Response:
    {
        "message": "Password changed successfully"
    }
    """
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request):
        serializer = ChangePasswordSerializer(
            data=request.data,
            context={'request': request}
        )
        
        if serializer.is_valid():
            serializer.save()
            return Response({
                'message': 'Password changed successfully'
            }, status=status.HTTP_200_OK)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class PasswordResetRequestView(APIView):
    """
    POST /api/auth/password-reset/
    
    Request password reset. Sends reset email if email service is configured.
    
    Request body:
    {
        "email": "user@example.com"
    }
    
    Response:
    {
        "message": "Password reset email sent if account exists"
    }
    
    Note: This is a basic implementation. For production, integrate with
    Django's password reset system or email service.
    """
    permission_classes = [permissions.AllowAny]
    
    def post(self, request):
        email = request.data.get('email')
        
        if not email:
            return Response({
                'error': 'Email is required'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Check if user exists
        try:
            user = User.objects.get(email=email)
            # In production, send password reset email here
            # For now, just return success message
            return Response({
                'message': 'If an account exists with this email, a password reset link has been sent.'
            }, status=status.HTTP_200_OK)
        except User.DoesNotExist:
            # Don't reveal if email exists or not (security best practice)
            return Response({
                'message': 'If an account exists with this email, a password reset link has been sent.'
            }, status=status.HTTP_200_OK)


class MeView(generics.RetrieveUpdateAPIView):
    """
    GET /api/me/
    PUT /api/me/
    PATCH /api/me/
    
    Get or update current authenticated user information.
    
    GET: Returns current user data
    PUT/PATCH: Updates current user (username, email, first_name, last_name)
    """
    permission_classes = [permissions.IsAuthenticated]
    
    def get_serializer_class(self):
        if self.request.method in ['PUT', 'PATCH']:
            return UserUpdateSerializer
        return UserSerializer

    def get_object(self):
        return self.request.user


class UserListView(generics.ListAPIView):
    """
    GET /api/users/
    
    List all users. Admin and staff only.
    
    Returns public profile information for all users.
    Supports pagination.
    """
    serializer_class = PublicUserSerializer
    permission_classes = [permissions.IsAdminUser]
    queryset = User.objects.all().order_by('-date_joined')
    
    def get_queryset(self):
        """Filter queryset if needed (e.g., search by username)"""
        queryset = super().get_queryset()
        username = self.request.query_params.get('username', None)
        if username:
            queryset = queryset.filter(username__icontains=username)
        return queryset


class UserDetailView(generics.RetrieveAPIView):
    """
    GET /api/users/{id}/
    
    Get public profile information for a specific user.
    
    Returns limited user information (no email, no sensitive data).
    Public endpoint (no authentication required).
    """
    serializer_class = PublicUserSerializer
    permission_classes = [permissions.AllowAny]
    queryset = User.objects.all()
    lookup_field = 'id'


class ProfileView(generics.RetrieveUpdateAPIView):
    """
    GET /api/me/profile/
    PUT /api/me/profile/
    PATCH /api/me/profile/
    
    Get or update current user's profile (first_name, last_name).
    
    GET: Returns current user's profile
    PUT/PATCH: Updates profile fields
    """
    serializer_class = ProfileSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_object(self):
        """Get or create profile for current user"""
        profile, created = Profile.objects.get_or_create(user=self.request.user)
        return profile


class MyMatchesView(generics.ListAPIView):
    """
    GET /api/my-matches/
    
    Get all matches where current user is creator or joiner.
    """
    serializer_class = MatchSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        return Match.objects.filter(creator=user) | Match.objects.filter(joiner=user)


class MatchListView(generics.ListAPIView):
    """
    GET /api/matches/

    List matches with optional filters. Defaults to all matches.

    Query params:
    - status
    - game
    - device
    - privacy
    - available=true (filters OPEN + PUBLIC)
    """
    serializer_class = MatchSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = Match.objects.select_related('creator', 'joiner', 'winner').order_by('-created_at')

        status_param = self.request.query_params.get('status')
        game_param = self.request.query_params.get('game')
        device_param = self.request.query_params.get('device')
        privacy_param = self.request.query_params.get('privacy')
        available_param = self.request.query_params.get('available')

        if status_param:
            queryset = queryset.filter(status=status_param)
        if game_param:
            queryset = queryset.filter(game=game_param)
        if device_param:
            queryset = queryset.filter(device=device_param)
        if privacy_param:
            queryset = queryset.filter(privacy=privacy_param)
        if available_param and available_param.lower() in ['1', 'true', 'yes']:
            queryset = queryset.filter(status='OPEN', privacy='PUBLIC')

        return queryset


class MatchDetailView(generics.RetrieveAPIView):
    """
    GET /api/matches/{id}/

    Retrieve match details. Private matches are restricted to participants.
    """
    serializer_class = MatchSerializer
    permission_classes = [permissions.IsAuthenticated]
    queryset = Match.objects.select_related('creator', 'joiner', 'winner')
    lookup_field = 'id'

    def get_object(self):
        match = super().get_object()
        user = self.request.user
        if match.privacy == 'PRIVATE' and user not in [match.creator, match.joiner]:
            raise PermissionDenied("You do not have access to this match.")
        return match


class MatchCreateView(APIView):
    """
    POST /api/matches/create/

    Create a new match and deduct stake from the creator's wallet.
    """
    permission_classes = [permissions.IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        serializer = MatchCreateSerializer(data=request.data, context={'request': request})
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        match = Match(**serializer.validated_data)
        match.creator = request.user
        match.save()

        wallet, _created = Wallet.objects.get_or_create(user=request.user)
        amount = Decimal(match.amount)
        old_balance = wallet.balance
        wallet.balance -= amount
        wallet.save(update_fields=['balance'])

        transaction_record = Transaction.objects.create(
            wallet=wallet,
            amount=-amount,
            transaction_type='MATCH_CREATION',
            description=f"Created {match.get_game_display()} match for ${match.amount}",
            related_match=match
        )

        try:
            from audit.utils import log_action
            log_action(
                action='match_created',
                user=request.user,
                details={
                    'match_id': match.id,
                    'game': match.game,
                    'device': match.device,
                    'amount': str(match.amount),
                    'creator_id': request.user.id,
                    'creator_username': request.user.username,
                    'joining_code': match.joining_code,
                    'wallet_id': wallet.id,
                    'old_balance': str(old_balance),
                    'new_balance': str(wallet.balance),
                    'transaction_id': transaction_record.id,
                },
                request=request,
            )
        except Exception:
            pass

        return Response(
            {
                'message': 'Match created successfully.',
                'match': MatchSerializer(match).data,
            },
            status=status.HTTP_201_CREATED,
        )


class MatchJoinView(APIView):
    """
    POST /api/matches/join/

    Join an existing match by code and deduct stake from the joiner's wallet.
    """
    permission_classes = [permissions.IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        serializer = MatchJoinSerializer(data=request.data, context={'request': request})
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        match = serializer.context['match']
        match = Match.objects.select_for_update().get(pk=match.pk)

        if match.status != 'OPEN' or match.joiner is not None:
            return Response(
                {'detail': 'Match is no longer available.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if match.creator == request.user:
            return Response(
                {'detail': 'You cannot join your own match.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        wallet, _created = Wallet.objects.get_or_create(user=request.user)
        if wallet.balance < Decimal(match.amount):
            return Response(
                {'detail': f"Insufficient funds. You need ${match.amount} to join this match."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        match.joiner = request.user
        match.status = 'JOINED'
        match.save(update_fields=['joiner', 'status'])

        amount = Decimal(match.amount)
        old_balance = wallet.balance
        wallet.balance -= amount
        wallet.save(update_fields=['balance'])

        transaction_record = Transaction.objects.create(
            wallet=wallet,
            amount=-amount,
            transaction_type='MATCH_JOINING',
            description=f"Joined {match.get_game_display()} match against {match.creator.username} for ${match.amount}",
            related_match=match
        )

        try:
            from audit.utils import log_action
            log_action(
                action='match_joined',
                user=request.user,
                details={
                    'match_id': match.id,
                    'game': match.game,
                    'device': match.device,
                    'amount': str(match.amount),
                    'creator_id': match.creator.id,
                    'creator_username': match.creator.username,
                    'joiner_id': request.user.id,
                    'joiner_username': request.user.username,
                    'joining_code': match.joining_code,
                    'wallet_id': wallet.id,
                    'old_balance': str(old_balance),
                    'new_balance': str(wallet.balance),
                    'transaction_id': transaction_record.id,
                },
                request=request,
            )
        except Exception:
            pass

        return Response(
            {
                'message': 'Match joined successfully.',
                'match': MatchSerializer(match).data,
            },
            status=status.HTTP_200_OK,
        )


class MatchResultSubmitView(APIView):
    """
    POST /api/matches/{id}/submit-result/

    Submit match result for creator or joiner.
    """
    permission_classes = [permissions.IsAuthenticated]

    @transaction.atomic
    def post(self, request, id):
        match = get_object_or_404(Match, id=id)

        if match.status != 'JOINED':
            return Response(
                {'detail': f"Cannot submit result for a match with status '{match.get_status_display()}'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if request.user != match.creator and request.user != match.joiner:
            return Response(
                {'detail': 'You are not a participant in this match.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = MatchResultSubmissionSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        submission = serializer.validated_data['submission']
        match_result, _created = MatchResult.objects.get_or_create(match=match)

        is_creator = request.user == match.creator
        if is_creator:
            if match_result.creator_submission:
                return Response(
                    {'detail': 'You have already submitted your result for this match.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            match_result.creator_submission = submission
            match_result.creator_submission_time = timezone.now()
        else:
            if match_result.joiner_submission:
                return Response(
                    {'detail': 'You have already submitted your result for this match.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            match_result.joiner_submission = submission
            match_result.joiner_submission_time = timezone.now()

        match_result.save()

        try:
            from audit.utils import log_action
            log_action(
                action='match_result_submitted',
                user=request.user,
                details={
                    'match_id': match.id,
                    'user_id': request.user.id,
                    'username': request.user.username,
                    'role': 'creator' if is_creator else 'joiner',
                    'submission': submission,
                    'submission_round': match_result.submission_round,
                },
                request=request,
            )
        except Exception:
            pass

        if not match_result.creator_submission or not match_result.joiner_submission:
            opponent = match.joiner if is_creator else match.creator
            Notification.objects.create(
                user=opponent,
                message=(
                    f"Your opponent has submitted their result for the {match.get_game_display()} "
                    f"match (${match.amount}). Please submit your result."
                )
            )
            return Response(
                {'message': 'Result submitted. Waiting for opponent.'},
                status=status.HTTP_200_OK,
            )

        creator_sub = match_result.creator_submission
        joiner_sub = match_result.joiner_submission

        if (creator_sub == 'WON' and joiner_sub == 'LOST') or \
           (creator_sub == 'LOST' and joiner_sub == 'WON') or \
           (creator_sub == 'DRAW' and joiner_sub == 'DRAW'):

            match.status = 'COMPLETED'

            if creator_sub == 'WON':
                winner = match.creator
                loser = match.joiner
            elif joiner_sub == 'WON':
                winner = match.joiner
                loser = match.creator
            else:
                refund_amount = Decimal(match.amount) * Decimal('0.9')
                creator_wallet = match.creator.wallet
                joiner_wallet = match.joiner.wallet

                creator_wallet.balance += refund_amount
                creator_wallet.save(update_fields=['balance'])
                joiner_wallet.balance += refund_amount
                joiner_wallet.save(update_fields=['balance'])

                Transaction.objects.create(
                    wallet=creator_wallet,
                    amount=refund_amount,
                    transaction_type='MATCH_DRAW_RETURN',
                    description=(
                        f"Return from draw in {match.get_game_display()} match against "
                        f"{match.joiner.username} for ${match.amount}"
                    ),
                    related_match=match
                )

                Transaction.objects.create(
                    wallet=joiner_wallet,
                    amount=refund_amount,
                    transaction_type='MATCH_DRAW_RETURN',
                    description=(
                        f"Return from draw in {match.get_game_display()} match against "
                        f"{match.creator.username} for ${match.amount}"
                    ),
                    related_match=match
                )

                Notification.objects.create(
                    user=match.creator,
                    message=(
                        f"Your {match.get_game_display()} match against {match.joiner.username} "
                        f"ended in a draw. ${refund_amount} has been returned to your wallet."
                    )
                )
                Notification.objects.create(
                    user=match.joiner,
                    message=(
                        f"Your {match.get_game_display()} match against {match.creator.username} "
                        f"ended in a draw. ${refund_amount} has been returned to your wallet."
                    )
                )

                match.save(update_fields=['status'])

                return Response(
                    {'message': 'Match recorded as a draw.', 'status': match.status},
                    status=status.HTTP_200_OK,
                )

            match.winner = winner
            match.save(update_fields=['status', 'winner'])

            winner_wallet = winner.wallet
            winner_wallet.balance += Decimal(match.winnings)
            winner_wallet.save(update_fields=['balance'])

            Transaction.objects.create(
                wallet=winner_wallet,
                amount=Decimal(match.winnings),
                transaction_type='MATCH_WINNINGS',
                description=(
                    f"Winnings from {match.get_game_display()} match against {loser.username} "
                    f"for ${match.amount}"
                ),
                related_match=match
            )

            Notification.objects.create(
                user=winner,
                message=(
                    f"Congratulations! You won the {match.get_game_display()} match against "
                    f"{loser.username}. ${match.winnings} has been added to your wallet."
                )
            )
            Notification.objects.create(
                user=loser,
                message=(
                    f"You lost the {match.get_game_display()} match against {winner.username}."
                )
            )

            return Response(
                {
                    'message': 'Match result recorded successfully.',
                    'status': match.status,
                    'winner_id': winner.id,
                },
                status=status.HTTP_200_OK,
            )

        if match_result.submission_round == 1:
            match_result.creator_submission = None
            match_result.creator_submission_time = None
            match_result.joiner_submission = None
            match_result.joiner_submission_time = None
            match_result.submission_round = 2
            match_result.save()

            Notification.objects.create(
                user=match.creator,
                message=(
                    f"Result disagreement detected for your {match.get_game_display()} match "
                    f"against {match.joiner.username}. Please submit results again (final attempt)."
                ),
            )
            Notification.objects.create(
                user=match.joiner,
                message=(
                    f"Result disagreement detected for your {match.get_game_display()} match "
                    f"against {match.creator.username}. Please submit results again (final attempt)."
                ),
            )

            return Response(
                {'message': 'Disagreement detected. Please submit results again.', 'round': 2},
                status=status.HTTP_200_OK,
            )

        match.status = 'DISPUTED'
        match.save(update_fields=['status'])

        try:
            from panel.models import Dispute
            Dispute.objects.create(match=match, status='OPEN')
        except Exception:
            pass

        Notification.objects.create(
            user=match.creator,
            message=(
                f"Your {match.get_game_display()} match against {match.joiner.username} "
                f"has been marked as DISPUTED after conflicting results. Support will review."
            ),
        )
        Notification.objects.create(
            user=match.joiner,
            message=(
                f"Your {match.get_game_display()} match against {match.creator.username} "
                f"has been marked as DISPUTED after conflicting results. Support will review."
            ),
        )

        return Response(
            {'message': 'Match marked as disputed. Support will review.', 'status': match.status},
            status=status.HTTP_200_OK,
        )


class MatchCancelView(APIView):
    """
    POST /api/matches/{id}/cancel/

    Cancel a match or leave a joined match. Handles refunds.
    """
    permission_classes = [permissions.IsAuthenticated]

    @transaction.atomic
    def post(self, request, id):
        match = get_object_or_404(Match, id=id)

        if request.user != match.creator and request.user != match.joiner:
            return Response(
                {'detail': "You don't have permission to cancel this match."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if match.status not in ['OPEN', 'JOINED']:
            return Response(
                {'detail': f"Cannot cancel a match with status '{match.get_status_display()}'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        match_game = match.get_game_display()
        match_amount = match.amount

        if request.user == match.creator:
            creator_wallet = match.creator.wallet
            creator_wallet.balance += Decimal(match.amount)
            creator_wallet.save(update_fields=['balance'])

            Transaction.objects.create(
                wallet=creator_wallet,
                amount=Decimal(match.amount),
                transaction_type='MATCH_REFUND',
                description=f"Refund from cancelled {match_game} match for ${match_amount}",
                related_match=match
            )

            if match.joiner:
                joiner = match.joiner
                joiner_wallet = joiner.wallet
                joiner_wallet.balance += Decimal(match.amount)
                joiner_wallet.save(update_fields=['balance'])

                Transaction.objects.create(
                    wallet=joiner_wallet,
                    amount=Decimal(match.amount),
                    transaction_type='MATCH_REFUND',
                    description=f"Refund from cancelled {match_game} match for ${match_amount}",
                    related_match=match
                )

                Notification.objects.create(
                    user=joiner,
                    message=(
                        f"A {match_game} match you joined has been cancelled by the creator. "
                        f"${match_amount} has been refunded to your wallet."
                    )
                )

            match.delete()

            return Response(
                {'message': 'Match cancelled and refunded.', 'status': 'CANCELLED'},
                status=status.HTTP_200_OK,
            )

        joiner_wallet = match.joiner.wallet
        joiner_wallet.balance += Decimal(match.amount)
        joiner_wallet.save(update_fields=['balance'])

        match.joiner = None
        match.status = 'OPEN'
        match.save(update_fields=['joiner', 'status'])

        Transaction.objects.create(
            wallet=joiner_wallet,
            amount=Decimal(match.amount),
            transaction_type='MATCH_REFUND',
            description=f"Refund from leaving {match_game} match for ${match_amount}",
            related_match=match
        )

        Notification.objects.create(
            user=match.creator,
            message=(
                f"{request.user.username} has left your {match_game} match. The match is now open."
            )
        )

        return Response(
            {'message': 'You have left the match and been refunded.', 'status': match.status},
            status=status.HTTP_200_OK,
        )


class WalletDetailView(generics.RetrieveAPIView):
    """
    GET /api/wallet/

    Return the authenticated user's wallet balance.
    """
    serializer_class = WalletSerializer
    permission_classes = [permissions.IsAuthenticated, IsWalletOwner]

    def get_object(self):
        wallet, _created = Wallet.objects.select_related('user').get_or_create(
            user=self.request.user
        )
        return wallet


class TransactionHistoryView(generics.ListAPIView):
    """
    GET /api/wallet/transactions/

    Return the authenticated user's wallet transactions.
    """
    serializer_class = TransactionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return (
            Transaction.objects.select_related('wallet', 'related_match')
            .filter(wallet__user=self.request.user)
            .order_by('-created_at')
        )


class DepositCreateView(APIView):
    """
    POST /api/wallet/deposit/

    Create a deposit request for the authenticated user.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = DepositCreateSerializer(data=request.data, context={'request': request})
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        deposit = serializer.save()

        from audit.utils import log_action
        log_action(
            action='deposit_created',
            user=request.user,
            details={
                'deposit_id': deposit.id,
                'amount': str(deposit.amount),
                'payment_method': deposit.payment_method,
                'status': deposit.status,
            },
            request=request,
        )

        return Response(
            {
                'deposit_id': deposit.id,
                'status': deposit.status,
                'amount': str(deposit.amount),
                'payment_method': deposit.payment_method,
                'message': 'Deposit request created. Payment processing pending.',
            },
            status=status.HTTP_201_CREATED,
        )


class WithdrawalCreateView(APIView):
    """
    POST /api/wallet/withdraw/

    Create a withdrawal request for the authenticated user.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = WithdrawalCreateSerializer(data=request.data, context={'request': request})
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        from wallet.error_handlers import _get_client_ip, detect_suspicious_withdrawal_activity, log_security_event
        suspicious, reasons = detect_suspicious_withdrawal_activity(
            request,
            serializer.validated_data['amount'],
            serializer.validated_data['payment_method'],
        )

        if suspicious:
            log_security_event(
                'suspicious_withdrawal_activity',
                {
                    'reasons': reasons,
                    'amount': float(serializer.validated_data['amount']),
                    'payment_method': serializer.validated_data['payment_method'],
                    'user_id': request.user.id,
                    'username': request.user.username,
                },
                request=request,
                severity='WARNING',
            )

        withdrawal = serializer.save()

        from audit.utils import log_action
        log_action(
            action='withdrawal_created',
            user=request.user,
            details={
                'withdrawal_id': withdrawal.id,
                'amount': str(withdrawal.amount),
                'payment_method': withdrawal.payment_method,
                'status': withdrawal.status,
                'suspicious': suspicious,
                'ip_address': _get_client_ip(request),
            },
            request=request,
        )

        notify_withdrawal_created(withdrawal)

        return Response(
            {
                'withdrawal_id': withdrawal.id,
                'status': withdrawal.status,
                'amount': str(withdrawal.amount),
                'payment_method': withdrawal.payment_method,
                'message': 'Withdrawal request created and queued for processing.',
            },
            status=status.HTTP_201_CREATED,
        )
