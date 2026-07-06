from rest_framework import generics, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.utils.decorators import method_decorator
from rest_framework.exceptions import PermissionDenied
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from decimal import Decimal
import logging
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter
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
    WithdrawalCreateSerializer,
    DisputeSerializer,
    DisputeResolutionSerializer,
    MessageSerializer,
    MessageCreateSerializer,
    NotificationSerializer
)
from .permissions import IsWalletOwner, IsMatchParticipant
from accounts.models import CustomUser, Profile
from matches.models import Match, MatchResult
from panel.models import Dispute
from messenger.models import Message, ReadMessage
from alert.models import Notification, ReadNotification
from wallet.models import Wallet, Transaction
from wallet.notifications import notify_withdrawal_created
from wallet.withdrawal_processing import process_withdrawal_now

User = get_user_model()
logger = logging.getLogger('payments.lipila')


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
    permission_classes = [permissions.IsAuthenticated, IsMatchParticipant]

    @transaction.atomic
    def post(self, request, id):
        match = get_object_or_404(Match, id=id)
        self.check_object_permissions(request, match)

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
    permission_classes = [permissions.IsAuthenticated, IsMatchParticipant]

    @transaction.atomic
    def post(self, request, id):
        match = get_object_or_404(Match, id=id)
        self.check_object_permissions(request, match)

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

        mobile_number = serializer.validated_data.get('mobile_number')
        deposit = serializer.save()

        from wallet.utils import initialize_deposit_payment, get_deposit_payment_status_payload
        payment = initialize_deposit_payment(deposit, request, mobile_number=mobile_number)

        from audit.utils import log_action
        log_action(
            action='deposit_created',
            user=request.user,
            details={
                'deposit_id': deposit.id,
                'amount': str(deposit.amount),
                'payment_method': deposit.payment_method,
                'status': deposit.status,
                'payment_initialized': payment.get('initialized'),
            },
            request=request,
        )

        response_status = (
            status.HTTP_201_CREATED
            if payment['success']
            else status.HTTP_400_BAD_REQUEST
        )
        payload = {
            **get_deposit_payment_status_payload(deposit),
            'message': payment['message'],
        }
        if payment.get('payment_url'):
            payload['payment_url'] = payment['payment_url']
        if payment.get('failure_reason'):
            payload['failure_reason'] = payment['failure_reason']

        return Response(payload, status=response_status)


class PaymentStatusView(APIView):
    """
    GET /api/payment/status/{order_id}/

    Poll deposit payment status (DB + optional server-side provider verification).
    Frontend must not assume payment success until status is COMPLETED.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, order_id):
        from wallet.models import Deposit
        from wallet.utils import get_deposit_payment_status_payload
        from services.payments.factory import get_payment_gateway
        from wallet.payment_processing import apply_deposit_webhook_status

        deposit = get_object_or_404(Deposit, id=order_id, user=request.user)

        if deposit.status in ('PENDING', 'PROCESSING') and deposit.payment_provider in ('lipila', 'zynle'):
            gateway = get_payment_gateway(deposit.payment_provider)
            verify = gateway.verify_payment(deposit)
            if verify.payment_status == 'Successful':
                apply_deposit_webhook_status(
                    deposit,
                    payment_status='Successful',
                    provider_transaction_id=verify.provider_transaction_id,
                    raw_payload=verify.raw_response,
                )
                deposit.refresh_from_db()
            elif verify.payment_status == 'Failed':
                apply_deposit_webhook_status(
                    deposit,
                    payment_status='Failed',
                    provider_transaction_id=verify.provider_transaction_id,
                    raw_payload=verify.raw_response,
                )
                deposit.refresh_from_db()

        return Response(get_deposit_payment_status_payload(deposit))


@method_decorator(csrf_exempt, name='dispatch')
class LipilaWebhookView(APIView):
    """
    POST /api/payments/lipila/webhook/

    Authoritative payment confirmation — idempotent wallet credit.
    """
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request):
        from services.payments.factory import get_payment_gateway
        from wallet.payment_debug import payment_debug_enabled

        raw_body = request.body or b''
        logger.info(
            'Lipila webhook HTTP hit: path=%s content_type=%s remote_addr=%s user_agent=%s bytes=%s',
            request.path,
            request.META.get('CONTENT_TYPE', ''),
            request.META.get('REMOTE_ADDR', ''),
            request.META.get('HTTP_USER_AGENT', ''),
            len(raw_body),
        )
        if payment_debug_enabled():
            logger.info(
                '[PAYMENT_DEBUG] lipila_webhook_raw: headers=%s body=%s',
                {
                    'content_type': request.META.get('CONTENT_TYPE', ''),
                    'x_signature': request.META.get('HTTP_X_SIGNATURE', ''),
                    'x_webhook_signature': request.META.get('HTTP_X_WEBHOOK_SIGNATURE', ''),
                    'webhook_signature': request.META.get('HTTP_WEBHOOK_SIGNATURE', ''),
                    'user_agent': request.META.get('HTTP_USER_AGENT', ''),
                },
                raw_body.decode('utf-8', errors='replace')[:4000],
            )

        gateway = get_payment_gateway('lipila')
        result = gateway.handle_webhook(request)
        logger.info(
            'Lipila webhook handled: processed=%s deposit_id=%s payment_status=%s message=%s',
            result.processed,
            result.deposit_id,
            result.payment_status,
            result.message,
        )
        if not result.processed and 'signature' in (result.message or '').lower():
            return Response({'status': 'error', 'message': result.message}, status=status.HTTP_401_UNAUTHORIZED)
        return Response(
            {
                'status': 'ok' if result.processed else 'ignored',
                'message': result.message,
                'deposit_id': result.deposit_id,
                'payment_status': result.payment_status,
            },
            status=status.HTTP_200_OK,
        )


@method_decorator(csrf_exempt, name='dispatch')
class ZynleWebhookView(APIView):
    """POST /api/payments/zynle/webhook/ — authoritative Zynle callback."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request):
        from services.payments.factory import get_payment_gateway

        result = get_payment_gateway('zynle').handle_webhook(request)
        if not result.processed and 'token' in (result.message or '').lower():
            return Response(
                {'status': 'error', 'message': result.message},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        return Response({
            'status': 'ok' if result.processed else 'ignored',
            'message': result.message,
            'deposit_id': result.deposit_id,
            'payment_status': result.payment_status,
        })


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

        process_result = None
        if (
            withdrawal.payment_method == 'MOBILE_MONEY'
            and getattr(settings, 'WALLET_AUTO_PROCESS_WITHDRAWALS', True)
        ):
            process_result = process_withdrawal_now(withdrawal, actor=request.user)
            withdrawal.refresh_from_db()

        return Response(
            {
                'withdrawal_id': withdrawal.id,
                'status': withdrawal.status,
                'amount': str(withdrawal.amount),
                'payment_method': withdrawal.payment_method,
                'transaction_id': withdrawal.transaction_id,
                'gateway_transaction_id': withdrawal.gateway_transaction_id,
                'message': (
                    process_result.get('message')
                    if process_result
                    else 'Withdrawal request created and queued for processing.'
                ),
            },
            status=status.HTTP_201_CREATED,
        )
@extend_schema_view(
    list=extend_schema(
        summary="List disputes",
        description="Get list of disputes. Support staff see all disputes, regular users see only disputes for their own matches.",
        parameters=[
            OpenApiParameter(
                name='status',
                type=str,
                location=OpenApiParameter.QUERY,
                description='Filter by status (OPEN, PENDING, RESOLVED)',
                required=False,
            ),
        ],
    ),
    retrieve=extend_schema(
        summary="Get dispute detail",
        description="Get detailed information about a specific dispute.",
    ),
    resolve=extend_schema(
        summary="Resolve dispute",
        description="Resolve a dispute. Only support staff can resolve disputes.",
        request=DisputeResolutionSerializer,
        responses={200: DisputeSerializer},
    ),
)
class DisputeViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing disputes.
    
    list: GET /api/disputes/ - List all disputes (support staff: all, users: own)
    retrieve: GET /api/disputes/{id}/ - Get dispute detail
    resolve: POST /api/disputes/{id}/resolve/ - Resolve a dispute (support staff only)
    """
    serializer_class = DisputeSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        """Filter disputes based on user role"""
        user = self.request.user
        
        # Support staff can see all disputes
        if user.is_support_staff or user.is_staff:
            queryset = Dispute.objects.all()
        else:
            # Regular users can only see disputes for their matches
            queryset = Dispute.objects.filter(
                match__creator=user
            ) | Dispute.objects.filter(
                match__joiner=user
            )
        
        # Filter by status if provided
        status_filter = self.request.query_params.get('status', None)
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        
        return queryset.order_by('-created_at')
    
    def get_permissions(self):
        """Override permissions for specific actions"""
        if self.action == 'resolve':
            # Only support staff can resolve disputes
            return [permissions.IsAuthenticated(), permissions.IsAdminUser()]
        # Regular users can list and retrieve their own disputes
        return [permissions.IsAuthenticated()]
    
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAdminUser])
    def resolve(self, request, pk=None):
        """
        POST /api/disputes/{id}/resolve/
        
        Resolve a dispute. Only support staff can resolve disputes.
        
        Request body:
        {
            "status": "RESOLVED",
            "resolution_notes": "Dispute resolved in favor of creator"
        }
        """
        dispute = self.get_object()
        serializer = DisputeResolutionSerializer(data=request.data)
        
        if serializer.is_valid():
            dispute.status = serializer.validated_data['status']
            dispute.resolution_notes = serializer.validated_data.get('resolution_notes', '')
            
            if dispute.status == 'RESOLVED':
                dispute.resolved_at = timezone.now()
            
            dispute.save()
            
            # Create notification for match participants
            match = dispute.match
            participants = [match.creator]
            if match.joiner:
                participants.append(match.joiner)
            
            for participant in participants:
                Notification.objects.create(
                    user=participant,
                    message=f"Dispute for match {dispute.match.joining_code} has been {dispute.get_status_display().lower()}."
                )
            
            return Response(
                DisputeSerializer(dispute).data,
                status=status.HTTP_200_OK
            )
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@extend_schema_view(
    list=extend_schema(
        summary="List messages",
        description="Get all messages where the current user is either sender or receiver.",
    ),
    create=extend_schema(
        summary="Send message",
        description="Send a new message to another user.",
        request=MessageCreateSerializer,
        responses={201: MessageSerializer},
    ),
    retrieve=extend_schema(
        summary="Get message detail",
        description="Get detailed information about a specific message.",
    ),
    conversations=extend_schema(
        summary="List conversations",
        description="Get all conversations with latest message and unread count for each conversation.",
    ),
    conversation=extend_schema(
        summary="Get conversation",
        description="Get all messages in a conversation with a specific user. Automatically marks received messages as read.",
    ),
)
class MessageViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing messages.
    
    list: GET /api/messages/ - List all messages (sent/received)
    create: POST /api/messages/ - Send a new message
    retrieve: GET /api/messages/{id}/ - Get message detail
    conversations: GET /api/messages/conversations/ - List all conversations
    conversation: GET /api/messages/conversation/{user_id}/ - Get conversation with a user
    """
    permission_classes = [permissions.IsAuthenticated]
    
    def get_serializer_class(self):
        """Use different serializers for different actions"""
        if self.action == 'create':
            return MessageCreateSerializer
        return MessageSerializer
    
    def get_queryset(self):
        """Get messages where user is sender or receiver"""
        user = self.request.user
        return (Message.objects.filter(sender=user) | 
                Message.objects.filter(receiver=user)).order_by('-created_at')
    
    def perform_create(self, serializer):
        """Set sender to current user and create notification"""
        serializer.save(sender=self.request.user)
        
        receiver = serializer.validated_data['receiver']
        Notification.objects.create(
            user=receiver,
            message=f"You have a new message from {self.request.user.username}"
        )
    
    @action(detail=False, methods=['get'])
    def conversations(self, request):
        """
        GET /api/messages/conversations/
        
        List all conversations (users you've messaged with).
        Returns list of users with latest message and unread count.
        """
        user = request.user
        User = get_user_model()
        
        # Get all users the current user has exchanged messages with
        conversations = User.objects.filter(
            Q(sent_messages__receiver=user) | 
            Q(received_messages__sender=user)
        ).distinct().exclude(id=user.id)
        
        conversation_data = []
        for other_user in conversations:
            # Get latest message
            latest_message = Message.objects.filter(
                (Q(sender=user) & Q(receiver=other_user)) |
                (Q(sender=other_user) & Q(receiver=user))
            ).order_by('-created_at').first()
            
            # Count unread messages
            unread_count = Message.objects.filter(
                sender=other_user,
                receiver=user
            ).exclude(
                id__in=ReadMessage.objects.filter(
                    receiver=user
                ).values_list('message_id', flat=True)
            ).count()
            
            conversation_data.append({
                'user_id': other_user.id,
                'username': other_user.username,
                'latest_message': MessageSerializer(
                    latest_message,
                    context={'request': request}
                ).data if latest_message else None,
                'unread_count': unread_count
            })
        
        return Response(conversation_data, status=status.HTTP_200_OK)
    
    @action(detail=False, methods=['get'], url_path='conversation/(?P<user_id>[^/.]+)')
    def conversation(self, request, user_id=None):
        """
        GET /api/messages/conversation/{user_id}/
        
        Get all messages in a conversation with a specific user.
        Marks messages as read when viewed.
        """
        User = get_user_model()
        other_user = get_object_or_404(User, id=user_id)
        
        # Get all messages between these two users
        messages = Message.objects.filter(
            (Q(sender=request.user) & Q(receiver=other_user)) |
            (Q(sender=other_user) & Q(receiver=request.user))
        ).order_by('created_at')
        
        # Mark all received messages as read
        unread_messages = Message.objects.filter(
            sender=other_user,
            receiver=request.user
        ).exclude(
            id__in=ReadMessage.objects.filter(
                receiver=request.user
            ).values_list('message_id', flat=True)
        )
        
        for msg in unread_messages:
            ReadMessage.objects.get_or_create(
                message=msg,
                receiver=request.user
            )
        
        serializer = MessageSerializer(messages, many=True, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)


@extend_schema_view(
    list=extend_schema(
        summary="List notifications",
        description="Get all notifications for the current user, ordered by most recent first.",
    ),
    retrieve=extend_schema(
        summary="Get notification detail",
        description="Get detailed information about a specific notification.",
    ),
    mark_read=extend_schema(
        summary="Mark notification as read",
        description="Mark a specific notification as read. Users can only mark their own notifications.",
    ),
    mark_all_read=extend_schema(
        summary="Mark all notifications as read",
        description="Mark all unread notifications for the current user as read.",
    ),
    unread_count=extend_schema(
        summary="Get unread count",
        description="Get count of unread notifications for the current user.",
    ),
)
class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for managing notifications.
    
    list: GET /api/notifications/ - List all notifications for current user
    retrieve: GET /api/notifications/{id}/ - Get notification detail
    mark_read: POST /api/notifications/{id}/mark-read/ - Mark notification as read
    mark_all_read: POST /api/notifications/mark-all-read/ - Mark all notifications as read
    unread_count: GET /api/notifications/unread-count/ - Get unread notification count
    """
    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        """Get notifications for current user only"""
        return Notification.objects.filter(
            user=self.request.user
        ).order_by('-created_at')
    
    @action(detail=True, methods=['post'])
    def mark_read(self, request, pk=None):
        """
        POST /api/notifications/{id}/mark-read/
        
        Mark a specific notification as read.
        """
        notification = self.get_object()
        
        # Ensure user can only mark their own notifications as read
        if notification.user != request.user:
            return Response(
                {'error': 'You can only mark your own notifications as read.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        ReadNotification.objects.get_or_create(
            notification=notification,
            user=request.user
        )
        
        return Response(
            {'message': 'Notification marked as read.'},
            status=status.HTTP_200_OK
        )
    
    @action(detail=False, methods=['post'])
    def mark_all_read(self, request):
        """
        POST /api/notifications/mark-all-read/
        
        Mark all notifications for current user as read.
        """
        unread_notifications = Notification.objects.filter(
            user=request.user
        ).exclude(
            id__in=ReadNotification.objects.filter(
                user=request.user
            ).values_list('notification_id', flat=True)
        )
        
        for notification in unread_notifications:
            ReadNotification.objects.get_or_create(
                notification=notification,
                user=request.user
            )
        
        return Response(
            {'message': f'{unread_notifications.count()} notifications marked as read.'},
            status=status.HTTP_200_OK
        )
    
    @action(detail=False, methods=['get'])
    def unread_count(self, request):
        """
        GET /api/notifications/unread-count/
        
        Get count of unread notifications for current user.
        """
        unread_count = Notification.objects.filter(
            user=request.user
        ).exclude(
            id__in=ReadNotification.objects.filter(
                user=request.user
            ).values_list('notification_id', flat=True)
        ).count()
        
        return Response(
            {'unread_count': unread_count},
            status=status.HTTP_200_OK
        )
