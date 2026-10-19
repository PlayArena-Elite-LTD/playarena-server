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
from django.db.models import Prefetch
from django.db.models import Max
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
    OrganisationLoginSerializer,
    OrganisationDirectorySerializer,
    OrganisationMembershipSerializer,
    OrganisationRegistrationSerializer,
    OrganisationSerializer,
    PlayerTournamentSerializer,
    UserRegistrationSerializer,
    ChangePasswordSerializer,
    WalletSerializer,
    OrganisationWalletSerializer,
    TransactionSerializer,
    OrganisationTransactionSerializer,
    DepositCreateSerializer,
    WithdrawalCreateSerializer,
    WithdrawalSerializer,
    PasswordResetConfirmSerializer,
    DisputeSerializer,
    DisputeResolutionSerializer,
    MessageSerializer,
    MessageCreateSerializer,
    NotificationSerializer,
    TournamentCreateSerializer,
    TournamentSerializer,
    TournamentRegistrationSerializer,
    TournamentPrizeInputSerializer,
    TournamentStandingSerializer,
    TournamentStandingInputSerializer,
    TournamentPayoutSerializer,
    TournamentMatchSerializer,
)
from .permissions import IsWalletOwner, IsMatchParticipant
from accounts.models import CustomUser, Organisation, OrganisationMembership, Profile
from matches.models import (
    Match, MatchResult, Tournament, TournamentRegistration, TournamentPrize,
    TournamentStanding, TournamentPayout, TournamentMatch, TournamentMatchSubmission,
)
from matches import brackets, leagues
from matches.tournament_fees import (
    clear_reserved_entry_split,
    confirm_full_tournament,
    recognize_tournament_fee,
    reverse_tournament_fee,
)
from panel.models import Dispute
from messenger.models import Message, ReadMessage
from alert.models import Notification, ReadNotification
from wallet.models import Wallet, Transaction, Withdrawal, OrganisationWallet, OrganisationTransaction
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

            # Referral attribution (spec section 3): a ?ref=CODE / referral_code
            # supplied at registration establishes a permanent referrer link.
            # Guarded so a bad code can never break account creation.
            try:
                from referrals.services import attribute_referral
                ref_code = (
                    request.data.get('referral_code')
                    or request.query_params.get('ref')
                )
                if ref_code:
                    attribute_referral(new_user=user, referral_code=ref_code)
            except Exception:  # pragma: no cover - defensive
                logger.exception("Referral attribution failed for user %s", user.id)

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


class OrganisationRegistrationView(APIView):
    """
    POST /api/auth/organisations/register/

    Register an organisation and return JWT tokens for the organisation owner.
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = OrganisationRegistrationSerializer(data=request.data)
        if serializer.is_valid():
            organisation = serializer.save()
            refresh = RefreshToken.for_user(organisation.owner)
            return Response({
                'organisation': OrganisationSerializer(organisation).data,
                'user': UserSerializer(organisation.owner).data,
                'access': str(refresh.access_token),
                'refresh': str(refresh),
            }, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class OrganisationLoginView(APIView):
    """
    POST /api/auth/organisations/login/

    Authenticate an organisation owner and return JWT tokens plus organisation data.
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = OrganisationLoginSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            organisation = serializer.validated_data['organisation']
            user = serializer.validated_data['user']
            refresh = RefreshToken.for_user(user)
            return Response({
                'organisation': OrganisationSerializer(organisation).data,
                'user': UserSerializer(user).data,
                'access': str(refresh.access_token),
                'refresh': str(refresh),
            }, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class OrganisationMeView(generics.RetrieveAPIView):
    """
    GET /api/organisations/me/

    Return the organisation attached to the authenticated owner account.
    """
    serializer_class = OrganisationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return get_object_or_404(Organisation, owner=self.request.user)


class OrganisationDirectoryListView(generics.ListAPIView):
    """
    GET /api/organisations/

    List organisations for players, including the current user's membership status.
    """
    serializer_class = OrganisationDirectorySerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user_membership = OrganisationMembership.objects.filter(player=self.request.user)
        return Organisation.objects.prefetch_related(
            Prefetch('memberships', queryset=user_membership, to_attr='current_user_memberships')
        ).order_by('name')


class OrganisationJoinRequestView(APIView):
    """
    POST /api/organisations/{id}/request-join/

    Request membership in an organisation. Rejected requests can be resubmitted.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, id):
        organisation = get_object_or_404(Organisation, id=id)
        if organisation.owner_id == request.user.id:
            return Response(
                {'detail': 'Organisation owners cannot request to join their own organisation.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        membership, created = OrganisationMembership.objects.get_or_create(
            organisation=organisation,
            player=request.user,
            defaults={'status': OrganisationMembership.Status.PENDING},
        )
        if not created and membership.status == OrganisationMembership.Status.REJECTED:
            membership.status = OrganisationMembership.Status.PENDING
            membership.reviewed_at = None
            membership.reviewed_by = None
            membership.save(update_fields=['status', 'reviewed_at', 'reviewed_by'])

        return Response(
            {
                'message': 'Join request submitted.',
                'membership': OrganisationMembershipSerializer(membership).data,
            },
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class PlayerTournamentListView(generics.ListAPIView):
    """
    GET /api/player/tournaments/

    List open tournaments from organisations where the player has approved membership.
    """
    serializer_class = PlayerTournamentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        approved_organisation_ids = OrganisationMembership.objects.filter(
            player=self.request.user,
            status=OrganisationMembership.Status.APPROVED,
        ).values('organisation_id')
        return Tournament.objects.select_related('organisation').filter(
            organisation_id__in=approved_organisation_ids,
            status='OPEN',
        ).order_by('-created_at')


class MyTournamentsView(generics.ListAPIView):
    """
    GET /api/player/tournaments/mine/

    Tournaments the player is currently registered in.
    """
    serializer_class = PlayerTournamentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        registered_ids = TournamentRegistration.objects.filter(
            player=self.request.user,
            status=TournamentRegistration.Status.REGISTERED,
        ).values('tournament_id')
        return Tournament.objects.select_related('organisation').filter(
            id__in=registered_ids,
        ).order_by('-created_at')


def _normalize_phone(raw):
    """Normalise a player's phone number to +<country code> form.

    Zambian local numbers (e.g. ``0974930662`` or ``974930662``) are stored with
    the ``+260`` country code as the spec requires; numbers already in
    international form are preserved.
    """
    import re
    digits = re.sub(r'[^0-9+]', '', str(raw or ''))
    if not digits:
        return ''
    if digits.startswith('+'):
        return '+' + re.sub(r'[^0-9]', '', digits[1:])
    if digits.startswith('00'):
        return '+' + digits[2:]
    if digits.startswith('260'):
        return '+' + digits
    if digits.startswith('0'):
        return '+260' + digits[1:]
    # Bare local subscriber number (Zambian mobile numbers are 9 digits).
    if len(digits) == 9:
        return '+260' + digits
    return '+260' + digits


class TournamentJoinView(APIView):
    """
    POST /api/player/tournaments/{id}/join/

    Join a tournament and deduct the participation amount from the player's wallet.
    Mirrors MatchJoinView: eligibility + funds + capacity checks inside an atomic,
    row-locked transaction, then a ledger Transaction, audit log, and notification.
    """
    permission_classes = [permissions.IsAuthenticated]

    @transaction.atomic
    def post(self, request, id):
        tournament = get_object_or_404(
            Tournament.objects.select_for_update().select_related('organisation'),
            id=id,
        )
        user = request.user

        # Standardised player metadata (spec 2): team name + WhatsApp/phone are
        # mandatory and captured per registration.
        team_name = str(request.data.get('team_name', '')).strip()
        phone = _normalize_phone(request.data.get('phone', ''))
        if not team_name:
            return Response(
                {'detail': 'Team name is required to join a tournament.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not phone or len(''.join(ch for ch in phone if ch.isdigit())) < 9:
            return Response(
                {'detail': 'A valid WhatsApp/phone number is required to join a tournament.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Auto-close registration if the deadline passed or capacity is reached.
        tournament.auto_close_registration()

        if tournament.registration_not_yet_open:
            return Response(
                {'detail': 'Registration for this tournament has not opened yet.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if tournament.status != 'OPEN' or tournament.past_registration_deadline:
            return Response(
                {'detail': 'Registration for this tournament is closed.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Eligibility: player must have approved membership in the organisation.
        is_member = OrganisationMembership.objects.filter(
            organisation=tournament.organisation,
            player=user,
            status=OrganisationMembership.Status.APPROVED,
        ).exists()
        if not is_member:
            return Response(
                {'detail': f"You must be an approved member of {tournament.organisation.name} to join."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Already registered?
        existing = TournamentRegistration.objects.filter(
            tournament=tournament, player=user,
        ).first()
        if existing and existing.status == TournamentRegistration.Status.REGISTERED:
            return Response(
                {'detail': 'You have already joined this tournament.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Capacity (locked count).
        active_count = TournamentRegistration.objects.filter(
            tournament=tournament,
            status=TournamentRegistration.Status.REGISTERED,
        ).count()
        if active_count >= tournament.max_players:
            return Response(
                {'detail': 'This tournament is already full.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        amount = Decimal(tournament.participation_amount)
        wallet, _created = Wallet.objects.get_or_create(user=user)
        wallet = Wallet.objects.select_for_update().get(pk=wallet.pk)
        if wallet.balance < amount:
            return Response(
                {'detail': f"Insufficient funds. You need ZMW {amount} to join this tournament."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Hold the entire entry in the tournament pool until capacity is full.
        # No PlayArena administration fee is allocated while players are still registering.
        platform_fee = Decimal('0.00')
        prize_contribution = amount

        # Create or reactivate the registration.
        if existing:
            existing.status = TournamentRegistration.Status.REGISTERED
            existing.amount_paid = amount
            existing.platform_fee = platform_fee
            existing.prize_contribution = prize_contribution
            existing.team_name = team_name
            existing.phone = phone
            existing.left_at = None
            existing.save(update_fields=[
                'status', 'amount_paid', 'platform_fee', 'prize_contribution',
                'team_name', 'phone', 'left_at',
            ])
            registration = existing
        else:
            registration = TournamentRegistration.objects.create(
                tournament=tournament,
                player=user,
                amount_paid=amount,
                platform_fee=platform_fee,
                prize_contribution=prize_contribution,
                team_name=team_name,
                phone=phone,
            )

        old_balance = wallet.balance
        wallet.balance -= amount
        wallet.save(update_fields=['balance'])

        transaction_record = Transaction.objects.create(
            wallet=wallet,
            amount=-amount,
            transaction_type='TOURNAMENT_JOINING',
            description=f"Joined tournament '{tournament.name}' for ZMW {amount}",
            related_tournament=tournament,
        )

        # The final seat triggers one tournament-wide, atomic settlement at
        # the organiser-selected PlayArena administration rate. The helper
        # snapshots gross/fee/net, distributes rounded cents exactly, and
        # moves the tournament to READY_TO_START.
        confirm_full_tournament(tournament)

        Notification.objects.create(
            user=user,
            message=f"You joined the tournament '{tournament.name}' for ZMW {amount}.",
            link='/tournaments',
        )

        try:
            from audit.utils import log_action
            log_action(
                action='tournament_joined',
                user=user,
                details={
                    'tournament_id': tournament.id,
                    'tournament_name': tournament.name,
                    'organisation_id': tournament.organisation_id,
                    'amount': str(amount),
                    'platform_fee': str(platform_fee),
                    'prize_contribution': str(prize_contribution),
                    'player_id': user.id,
                    'player_username': user.username,
                    'registration_id': registration.id,
                    'wallet_id': wallet.id,
                    'old_balance': str(old_balance),
                    'new_balance': str(wallet.balance),
                    'transaction_id': transaction_record.id,
                },
                request=request,
            )
        except Exception:
            pass

        tournament.refresh_from_db()
        return Response(
            {
                'message': 'Tournament joined successfully.',
                'tournament': PlayerTournamentSerializer(tournament, context={'request': request}).data,
            },
            status=status.HTTP_200_OK,
        )


class TournamentLeaveView(APIView):
    """
    POST /api/player/tournaments/{id}/leave/

    Leave a tournament while it is still OPEN and refund the participation amount.
    """
    permission_classes = [permissions.IsAuthenticated]

    @transaction.atomic
    def post(self, request, id):
        tournament = get_object_or_404(
            Tournament.objects.select_for_update().select_related('organisation'),
            id=id,
        )
        user = request.user

        registration = TournamentRegistration.objects.filter(
            tournament=tournament,
            player=user,
            status=TournamentRegistration.Status.REGISTERED,
        ).first()
        if not registration:
            return Response(
                {'detail': 'You are not registered for this tournament.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if tournament.status not in Tournament.PRE_PLAY_STATUSES:
            return Response(
                {'detail': 'You can only leave a tournament before it starts.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        amount = Decimal(registration.amount_paid)
        registration.status = TournamentRegistration.Status.WITHDRAWN
        registration.left_at = timezone.now()
        registration.save(update_fields=['status', 'left_at'])

        wallet, _created = Wallet.objects.get_or_create(user=user)
        old_balance = wallet.balance
        wallet.balance += amount
        wallet.save(update_fields=['balance'])

        transaction_record = Transaction.objects.create(
            wallet=wallet,
            amount=amount,
            transaction_type='TOURNAMENT_REFUND',
            description=f"Left tournament '{tournament.name}', ZMW {amount} refunded",
            related_tournament=tournament,
        )

        if tournament.status == 'READY_TO_START':
            # A pre-launch withdrawal invalidates the full-capacity fee
            # reservation. Restore gross contributions and reopen registration.
            reverse_tournament_fee(tournament, refunded=False)
            clear_reserved_entry_split(tournament)
            tournament.status = (
                'REG_CLOSED' if tournament.past_registration_deadline else 'OPEN'
            )
            tournament.save(update_fields=['status'])

        Notification.objects.create(
            user=user,
            message=f"You left the tournament '{tournament.name}'. ZMW {amount} has been refunded.",
            link='/tournaments',
        )

        try:
            from audit.utils import log_action
            log_action(
                action='tournament_left',
                user=user,
                details={
                    'tournament_id': tournament.id,
                    'tournament_name': tournament.name,
                    'amount': str(amount),
                    'player_id': user.id,
                    'player_username': user.username,
                    'registration_id': registration.id,
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
                'message': 'You have left the tournament and been refunded.',
                'tournament': PlayerTournamentSerializer(tournament, context={'request': request}).data,
            },
            status=status.HTTP_200_OK,
        )


class OrganisationMembershipRequestListView(generics.ListAPIView):
    """
    GET /api/organisations/membership-requests/

    List membership requests for the authenticated organiser's organisation.
    """
    serializer_class = OrganisationMembershipSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_organisation(self):
        try:
            return self.request.user.organisation
        except Organisation.DoesNotExist as exc:
            raise PermissionDenied("Only organisation accounts can review membership requests.") from exc

    def get_queryset(self):
        return OrganisationMembership.objects.select_related('player', 'organisation', 'reviewed_by').filter(
            organisation=self.get_organisation(),
        ).order_by('-requested_at')


class OrganisationMembershipReviewView(APIView):
    """
    POST /api/organisations/membership-requests/{id}/approve/
    POST /api/organisations/membership-requests/{id}/reject/
    """
    permission_classes = [permissions.IsAuthenticated]
    review_status = None

    def post(self, request, id):
        try:
            organisation = request.user.organisation
        except Organisation.DoesNotExist as exc:
            raise PermissionDenied("Only organisation accounts can review membership requests.") from exc

        membership = get_object_or_404(
            OrganisationMembership.objects.select_related('player', 'organisation'),
            id=id,
            organisation=organisation,
        )
        membership.status = self.review_status
        membership.reviewed_at = timezone.now()
        membership.reviewed_by = request.user
        membership.save(update_fields=['status', 'reviewed_at', 'reviewed_by'])
        return Response(OrganisationMembershipSerializer(membership).data, status=status.HTTP_200_OK)


class OrganisationMembershipApproveView(OrganisationMembershipReviewView):
    review_status = OrganisationMembership.Status.APPROVED


class OrganisationMembershipRejectView(OrganisationMembershipReviewView):
    review_status = OrganisationMembership.Status.REJECTED


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


class OrganisationPasswordResetRequestView(APIView):
    """
    POST /api/auth/organisations/password-reset/

    Start a password reset for an ORGANISER account. If the email belongs to an
    active organisation owner, a reset link (Django one-time token) is emailed.
    The response is always neutral so account existence is never revealed.

    Body: {"email": "owner@org.com"}
    """
    permission_classes = [permissions.AllowAny]

    NEUTRAL_MESSAGE = (
        'If an organisation account exists for this email, a password reset '
        'link has been sent.'
    )

    def post(self, request):
        email = str(request.data.get('email', '')).strip().lower()
        if not email:
            return Response({'error': 'Email is required.'}, status=status.HTTP_400_BAD_REQUEST)

        # Match either the owner's login email OR the organisation's own
        # contact email, so organisers can use whichever they remember. The
        # reset link is always sent to the owner's login email (the credential
        # being reset).
        user = (
            User.objects.filter(is_active=True)
            .filter(Q(email__iexact=email) | Q(organisation__email__iexact=email))
            .distinct()
            .first()
        )
        if user and Organisation.objects.filter(owner=user).exists():
            self._send_reset_email(user, request)

        return Response({'message': self.NEUTRAL_MESSAGE}, status=status.HTTP_200_OK)

    def _send_reset_email(self, user, request):
        from django.contrib.auth.tokens import default_token_generator
        from django.utils.http import urlsafe_base64_encode
        from django.utils.encoding import force_bytes
        from django.core.mail import send_mail

        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)

        base = (getattr(settings, 'FRONTEND_ORIGIN', '') or '').rstrip('/')
        if not base:
            base = request.build_absolute_uri('/').rstrip('/')
        link = f"{base}/organisations/reset-password?uid={uid}&token={token}"

        organisation = Organisation.objects.filter(owner=user).first()
        org_name = organisation.name if organisation else 'your organisation'
        subject = 'Reset your PlayArena organiser password'
        body = (
            f"Hello,\n\n"
            f"We received a request to reset the password for the PlayArena "
            f"organiser account for {org_name}.\n\n"
            f"Use the link below to choose a new password (the link expires for "
            f"your security):\n{link}\n\n"
            f"If you didn't request this, you can safely ignore this email — your "
            f"password won't change.\n\n— PlayArena"
        )
        from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', '') or None
        try:
            sent = send_mail(subject, body, from_email, [user.email], fail_silently=False)
            logger.info("Password reset email sent to %s (result=%s)", user.email, sent)
        except Exception as exc:  # log the real SMTP error but keep the response neutral
            logger.warning("Password reset email FAILED for %s: %s", user.email, exc)

        try:
            from audit.utils import log_action
            log_action(
                action='organisation_password_reset_requested',
                user=user,
                details={'email': user.email, 'organisation': org_name},
                request=request,
            )
        except Exception:
            pass


class OrganisationPasswordResetConfirmView(APIView):
    """
    POST /api/auth/organisations/password-reset/confirm/

    Complete an organiser password reset. Validates the uid + one-time token
    from the emailed link and sets the new password.

    Body: {"uid", "token", "new_password", "new_password_confirm"}
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            try:
                from audit.utils import log_action
                log_action(
                    action='organisation_password_reset_completed',
                    user=user,
                    details={'email': user.email},
                    request=request,
                )
            except Exception:
                pass
            return Response(
                {'message': 'Your password has been reset. You can now log in with your new password.'},
                status=status.HTTP_200_OK,
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


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
            description=f"Created {match.get_game_display()} match for ZMW {match.amount}",
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
                {'detail': f"Insufficient funds. You need ZMW {match.amount} to join this match."},
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
            description=f"Joined {match.get_game_display()} match against {match.creator.username} for ZMW {match.amount}",
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
                    f"match (ZMW {match.amount}). Please submit your result."
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

            if creator_sub == 'WON':
                winner = match.creator
                loser = match.joiner
            elif joiner_sub == 'WON':
                winner = match.joiner
                loser = match.creator
            else:
                from matches.settlement import settle_match
                match = settle_match(match, draw=True)
                refund_amount = Decimal(match.amount) * Decimal('0.9')
                Notification.objects.create(
                    user=match.creator,
                    message=(
                        f"Your {match.get_game_display()} match against {match.joiner.username} "
                        f"ended in a draw. ZMW {refund_amount} has been returned to your wallet."
                    )
                )
                Notification.objects.create(
                    user=match.joiner,
                    message=(
                        f"Your {match.get_game_display()} match against {match.creator.username} "
                        f"ended in a draw. ZMW {refund_amount} has been returned to your wallet."
                    )
                )

                return Response(
                    {'message': 'Match recorded as a draw.', 'status': match.status},
                    status=status.HTTP_200_OK,
                )

            from matches.settlement import settle_match
            match = settle_match(match, winner=winner)

            Notification.objects.create(
                user=winner,
                message=(
                    f"Congratulations! You won the {match.get_game_display()} match against "
                    f"{loser.username}. ZMW {match.winnings} has been added to your wallet."
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

        if match.status == 'JOINED':
            return Response(
                {
                    'detail': (
                        "Cannot cancel or leave a joined match. "
                        "Both players must submit results first."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if match.status != 'OPEN':
            return Response(
                {'detail': f"Cannot cancel a match with status '{match.get_status_display()}'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        result = MatchResult.objects.filter(match=match).first()
        if result and (result.creator_submission or result.joiner_submission):
            return Response(
                {'detail': "This match can't be cancelled because a result has already been submitted."},
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
                description=f"Refund from cancelled {match_game} match for ZMW {match_amount}",
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
                    description=f"Refund from cancelled {match_game} match for ZMW {match_amount}",
                    related_match=match
                )

                Notification.objects.create(
                    user=joiner,
                    message=(
                        f"A {match_game} match you joined has been cancelled by the creator. "
                        f"ZMW {match_amount} has been refunded to your wallet."
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
            description=f"Refund from leaving {match_game} match for ZMW {match_amount}",
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


class OrganisationTournamentListCreateView(generics.ListCreateAPIView):
    """
    GET /api/organisations/tournaments/
    POST /api/organisations/tournaments/

    List and create tournaments for the authenticated organiser's organisation.
    Tournaments are restricted to that organisation's players when join flows are added.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get_organisation(self):
        try:
            return self.request.user.organisation
        except Organisation.DoesNotExist as exc:
            raise PermissionDenied("Only organisation accounts can manage tournaments.") from exc

    def get_queryset(self):
        return Tournament.objects.select_related('organisation').filter(
            organisation=self.get_organisation()
        ).order_by('-created_at')

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return TournamentCreateSerializer
        return TournamentSerializer

    def perform_create(self, serializer):
        organisation = self.get_organisation()
        tournament = serializer.save(organisation=organisation)
        self._announce_new_tournament(tournament, organisation)

    def _announce_new_tournament(self, tournament, organisation):
        """Notify + push every approved member that a new tournament is open."""
        from alert.notify import notify
        members = OrganisationMembership.objects.select_related('player').filter(
            organisation=organisation,
            status=OrganisationMembership.Status.APPROVED,
        )
        label = '7-day league' if tournament.format == 'LEAGUE' else 'knockout'
        for membership in members:
            notify(
                membership.player,
                f"{organisation.name} just opened a new {label} tournament: '{tournament.name}'. Registration is open — join now.",
                link='/tournaments',
                subject=f"New tournament from {organisation.name}",
            )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        output_serializer = TournamentSerializer(
            serializer.instance,
            context=self.get_serializer_context(),
        )
        return Response(output_serializer.data, status=status.HTTP_201_CREATED)


class OrganisationTournamentRegistrationsView(generics.ListAPIView):
    """
    GET /api/organisations/tournaments/{id}/registrations/

    List the players registered for one of the authenticated organiser's
    tournaments. Only the organisation that owns the tournament may view it.
    """
    serializer_class = TournamentRegistrationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_organisation(self):
        try:
            return self.request.user.organisation
        except Organisation.DoesNotExist as exc:
            raise PermissionDenied("Only organisation accounts can view registrations.") from exc

    def get_queryset(self):
        tournament = get_object_or_404(
            Tournament,
            id=self.kwargs['id'],
            organisation=self.get_organisation(),
        )
        return TournamentRegistration.objects.select_related('player', 'player__profile').filter(
            tournament=tournament,
            status=TournamentRegistration.Status.REGISTERED,
        ).order_by('joined_at')


class OrganisationTournamentPrizesView(APIView):
    """
    PUT /api/organisations/tournaments/{id}/prizes/

    Replace the configured prize distribution for one of the authenticated
    organiser's tournaments. Accepts {"prizes": [{"position": 1,
    "percentage": "60"}, ...]}. Only allowed before the tournament starts.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get_organisation(self):
        try:
            return self.request.user.organisation
        except Organisation.DoesNotExist as exc:
            raise PermissionDenied("Only organisation accounts can configure prizes.") from exc

    @transaction.atomic
    def put(self, request, id):
        tournament = get_object_or_404(
            Tournament,
            id=id,
            organisation=self.get_organisation(),
        )
        if tournament.status not in Tournament.PRE_PLAY_STATUSES:
            return Response(
                {'detail': 'Prizes can only be changed before the tournament starts.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        input_serializer = TournamentPrizeInputSerializer(data=request.data.get('prizes', []), many=True)
        input_serializer.is_valid(raise_exception=True)
        prizes = input_serializer.validated_data

        positions = [p['position'] for p in prizes]
        if len(positions) != len(set(positions)):
            return Response(
                {'detail': 'Prize positions must be unique.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        total = sum((p['percentage'] for p in prizes), Decimal('0'))
        if total > Decimal('100'):
            return Response(
                {'detail': f"Total prize distribution is {total}%, which exceeds 100% of the pool."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        tournament.prizes.all().delete()
        for prize in prizes:
            TournamentPrize.objects.create(
                tournament=tournament,
                position=prize['position'],
                percentage=prize['percentage'],
            )

        return Response(
            TournamentSerializer(tournament, context={'request': request}).data,
            status=status.HTTP_200_OK,
        )


def _process_tournament_payout(payout, request=None):
    """Credit a single payout to the winner's wallet.

    Runs in its own atomic block so a failure marks the payout FAILED (with a
    reason) and leaves the record intact for later resolution — winnings are
    never lost. Idempotent: an already-PAID payout is left untouched.
    """
    try:
        with transaction.atomic():
            Wallet.objects.get_or_create(user=payout.player)
            wallet = Wallet.objects.select_for_update().get(user=payout.player)
            locked = TournamentPayout.objects.select_for_update().get(id=payout.id)
            if locked.status == TournamentPayout.Status.PAID:
                return locked

            old_balance = wallet.balance
            wallet.balance += locked.amount
            wallet.save(update_fields=['balance'])

            txn = Transaction.objects.create(
                wallet=wallet,
                amount=locked.amount,
                transaction_type='TOURNAMENT_WINNINGS',
                description=(
                    f"Tournament '{locked.tournament.name}' winnings — "
                    f"position {locked.position}"
                ),
                related_tournament=locked.tournament,
            )

            locked.status = TournamentPayout.Status.PAID
            locked.transaction = txn
            locked.paid_at = timezone.now()
            locked.failure_reason = ''
            locked.save(update_fields=['status', 'transaction', 'paid_at', 'failure_reason'])

            from alert.notify import notify
            notify(
                locked.player,
                (
                    f"You won ZMW {locked.amount} (position {locked.position}) in "
                    f"'{locked.tournament.name}'. It's been credited to your wallet."
                ),
                link='/tournaments',
                email=True,
                subject=f"You won a prize in {locked.tournament.name}",
            )

            try:
                from audit.utils import log_action
                log_action(
                    action='tournament_payout_paid',
                    user=locked.player,
                    details={
                        'tournament_id': locked.tournament_id,
                        'tournament_name': locked.tournament.name,
                        'payout_id': locked.id,
                        'position': locked.position,
                        'amount': str(locked.amount),
                        'player_id': locked.player_id,
                        'wallet_id': wallet.id,
                        'old_balance': str(old_balance),
                        'new_balance': str(wallet.balance),
                        'transaction_id': txn.id,
                    },
                    request=request,
                )
            except Exception:
                pass
            return locked
    except Exception as exc:  # noqa: BLE001 — record failure, keep it traceable
        TournamentPayout.objects.filter(id=payout.id).update(
            status=TournamentPayout.Status.FAILED,
            failure_reason=str(exc)[:500],
        )
        return None


def _settle_tournament_if_paid(tournament):
    """Flip a paying-out tournament to PAID once every payout is settled."""
    if tournament.status != 'PAYOUT_PROCESSING':
        return
    payouts = tournament.payouts.all()
    if payouts and all(p.status == TournamentPayout.Status.PAID for p in payouts):
        tournament.status = 'PAID'
        tournament.save(update_fields=['status'])


def _accrue_tournament_commissions(tournament):
    """Accrue referral commission for a settled tournament (spec section 2).

    Runs once at lock time, when entry fees are realised and no longer
    refundable. Commission is based on each referred entrant's own
    ``platform_fee`` (funded strictly from platform-fee revenue, never the prize
    pool). Idempotent per (tournament, entrant) via the referrals service.
    """
    try:
        from referrals.services import accrue_commission
        registrations = tournament.registrations.filter(status='REGISTERED').select_related('player')
        for reg in registrations:
            if reg.platform_fee and reg.platform_fee > 0:
                accrue_commission(
                    referred_user=reg.player,
                    platform_fee=reg.platform_fee,
                    related_tournament=tournament,
                )
    except Exception:  # pragma: no cover - defensive; must never block lock/payout
        logger.exception("Referral accrual failed for tournament %s", getattr(tournament, "id", None))



class OrganisationTournamentStandingsView(APIView):
    """
    GET  /api/organisations/tournaments/{id}/standings/
    PUT  /api/organisations/tournaments/{id}/standings/

    View or replace the (draft) final standings for one of the organiser's
    tournaments. PUT accepts {"standings": [{"player_id", "position",
    "points"?}, ...]} and is allowed until the tournament is locked.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get_organisation(self):
        try:
            return self.request.user.organisation
        except Organisation.DoesNotExist as exc:
            raise PermissionDenied("Only organisation accounts can manage standings.") from exc

    def get_tournament(self, id):
        return get_object_or_404(Tournament, id=id, organisation=self.get_organisation())

    def get(self, request, id):
        tournament = self.get_tournament(id)
        standings = tournament.standings.select_related('player', 'player__profile').all()
        return Response(TournamentStandingSerializer(standings, many=True).data)

    @transaction.atomic
    def put(self, request, id):
        tournament = self.get_tournament(id)
        if tournament.status in Tournament.TERMINAL_STATUSES:
            return Response(
                {'detail': 'Standings can no longer be changed for this tournament.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        input_serializer = TournamentStandingInputSerializer(
            data=request.data.get('standings', []), many=True,
        )
        input_serializer.is_valid(raise_exception=True)
        rows = input_serializer.validated_data

        positions = [r['position'] for r in rows]
        player_ids = [r['player_id'] for r in rows]
        if len(positions) != len(set(positions)):
            return Response({'detail': 'Positions must be unique.'}, status=status.HTTP_400_BAD_REQUEST)
        if len(player_ids) != len(set(player_ids)):
            return Response({'detail': 'Each player can only appear once.'}, status=status.HTTP_400_BAD_REQUEST)

        # Every ranked player must be an active participant of this tournament.
        registered_ids = set(
            TournamentRegistration.objects.filter(
                tournament=tournament,
                status=TournamentRegistration.Status.REGISTERED,
            ).values_list('player_id', flat=True)
        )
        invalid = [pid for pid in player_ids if pid not in registered_ids]
        if invalid:
            return Response(
                {'detail': f"These players are not registered for this tournament: {invalid}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        tournament.standings.all().delete()
        for row in rows:
            TournamentStanding.objects.create(
                tournament=tournament,
                player_id=row['player_id'],
                position=row['position'],
                points=row.get('points'),
            )

        standings = tournament.standings.select_related('player', 'player__profile').all()
        return Response(TournamentStandingSerializer(standings, many=True).data)


class OrganisationTournamentLockView(APIView):
    """
    POST /api/organisations/tournaments/{id}/lock/

    Lock final results and pay out automatically. Freezes standings, sets the
    tournament COMPLETED, and credits each configured prize position from the
    prize pool. Payout records are created first (traceable) and each credit is
    processed in isolation so a single failure never loses winnings.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get_organisation(self):
        try:
            return self.request.user.organisation
        except Organisation.DoesNotExist as exc:
            raise PermissionDenied("Only organisation accounts can lock tournaments.") from exc

    def post(self, request, id):
        organisation = self.get_organisation()
        with transaction.atomic():
            tournament = get_object_or_404(
                Tournament.objects.select_for_update(),
                id=id,
                organisation=organisation,
            )
            if tournament.status in Tournament.TERMINAL_STATUSES:
                already = 'already locked' if tournament.status != 'CANCELLED' else 'cancelled'
                return Response(
                    {'detail': f'This tournament is {already} and cannot be locked.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if tournament.status not in ('LIVE', 'RESULTS_PENDING'):
                return Response(
                    {'detail': 'Only a started tournament can have final results locked.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            standings = list(tournament.standings.select_related('player').all())
            if not standings:
                return Response(
                    {'detail': 'Enter final standings before locking the tournament.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            prizes = list(tournament.prizes.all())
            standing_by_position = {s.position: s for s in standings}
            missing = [p.position for p in prizes if p.position not in standing_by_position]
            if missing:
                return Response(
                    {'detail': f"Prize positions {missing} have no ranked player. Fix standings or prizes first."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            pool = tournament.prize_pool  # snapshot at lock time
            pending_payouts = []
            for prize in prizes:
                standing = standing_by_position[prize.position]
                amount = prize.expected_amount(pool)
                payout, _created = TournamentPayout.objects.get_or_create(
                    tournament=tournament,
                    position=prize.position,
                    defaults={'player': standing.player, 'amount': amount},
                )
                if payout.status != TournamentPayout.Status.PAID:
                    pending_payouts.append(payout)

            # COMPLETED = final standings locked; move to PAYOUT_PROCESSING while
            # winnings are credited (skipped straight to PAID if nothing to pay).
            tournament.status = 'PAYOUT_PROCESSING' if pending_payouts else 'PAID'
            tournament.save(update_fields=['status'])

            try:
                from audit.utils import log_action
                log_action(
                    action='tournament_locked',
                    user=request.user,
                    details={
                        'tournament_id': tournament.id,
                        'tournament_name': tournament.name,
                        'organisation_id': organisation.id,
                        'prize_pool': str(pool),
                        'payout_count': len(pending_payouts),
                    },
                    request=request,
                )
            except Exception:
                pass

        # Process credits after the lock commits so failures stay traceable.
        for payout in pending_payouts:
            _process_tournament_payout(payout, request=request)

        _settle_tournament_if_paid(tournament)
        # Referral commission on realised entry fees (spec section 2)
        _accrue_tournament_commissions(tournament)
        tournament.refresh_from_db()

        payouts = tournament.payouts.select_related('player', 'player__profile', 'transaction').all()
        all_paid = all(p.status == TournamentPayout.Status.PAID for p in payouts)
        return Response(
            {
                'message': (
                    'Final results locked. All winnings have been paid out.'
                    if all_paid else
                    'Final results locked. Some payouts need attention — see failed payouts.'
                ),
                'tournament': TournamentSerializer(tournament, context={'request': request}).data,
                'payouts': TournamentPayoutSerializer(payouts, many=True).data,
            },
            status=status.HTTP_200_OK,
        )


class OrganisationTournamentPayoutsView(APIView):
    """
    GET  /api/organisations/tournaments/{id}/payouts/

    List payout records (paid / pending / failed) for one of the organiser's
    tournaments so they can reconcile and spot failures.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get_organisation(self):
        try:
            return self.request.user.organisation
        except Organisation.DoesNotExist as exc:
            raise PermissionDenied("Only organisation accounts can view payouts.") from exc

    def get(self, request, id):
        tournament = get_object_or_404(Tournament, id=id, organisation=self.get_organisation())
        payouts = tournament.payouts.select_related('player', 'player__profile', 'transaction').all()
        return Response(TournamentPayoutSerializer(payouts, many=True).data)


class OrganisationTournamentPayoutRetryView(APIView):
    """
    POST /api/organisations/tournaments/{id}/payouts/{payout_id}/retry/

    Retry a FAILED payout. The record already exists, so this only re-attempts
    the wallet credit — winnings are never re-created or lost.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get_organisation(self):
        try:
            return self.request.user.organisation
        except Organisation.DoesNotExist as exc:
            raise PermissionDenied("Only organisation accounts can retry payouts.") from exc

    def post(self, request, id, payout_id):
        tournament = get_object_or_404(Tournament, id=id, organisation=self.get_organisation())
        payout = get_object_or_404(TournamentPayout, id=payout_id, tournament=tournament)
        if payout.status == TournamentPayout.Status.PAID:
            return Response(
                {'detail': 'This payout has already been paid.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        _process_tournament_payout(payout, request=request)
        _settle_tournament_if_paid(tournament)
        payout.refresh_from_db()
        return Response(TournamentPayoutSerializer(payout).data, status=status.HTTP_200_OK)


def _refund_all_registrations(tournament, request=None):
    """Refund every active registration's entry fee to the player's wallet."""
    active = tournament.registrations.select_related('player').filter(
        status=TournamentRegistration.Status.REGISTERED,
    )
    for registration in active:
        amount = Decimal(registration.amount_paid)
        registration.status = TournamentRegistration.Status.WITHDRAWN
        registration.left_at = timezone.now()
        registration.save(update_fields=['status', 'left_at'])

        Wallet.objects.get_or_create(user=registration.player)
        wallet = Wallet.objects.select_for_update().get(user=registration.player)
        wallet.balance += amount
        wallet.save(update_fields=['balance'])

        Transaction.objects.create(
            wallet=wallet,
            amount=amount,
            transaction_type='TOURNAMENT_REFUND',
            description=f"Tournament '{tournament.name}' cancelled — ZMW {amount} refunded",
            related_tournament=tournament,
        )
        from alert.notify import notify
        notify(
            registration.player,
            f"'{tournament.name}' was cancelled. Your entry of ZMW {amount} has been refunded.",
            link='/tournaments',
            email=True,
            subject=f"{tournament.name} was cancelled — you've been refunded",
        )


class OrganisationTournamentLifecycleView(APIView):
    """
    POST /api/organisations/tournaments/{id}/lifecycle/

    Manual lifecycle transitions for an organiser's tournament.
    Body: {"action": "publish" | "open" | "close_registration" | "schedule" | "cancel"}.
    Cancelling refunds every registered player's entry fee.
    """
    permission_classes = [permissions.IsAuthenticated]

    # action -> (allowed-from statuses, resulting status)
    TRANSITIONS = {
        'publish': (('DRAFT',), 'OPEN'),
        'open': (('DRAFT', 'REG_CLOSED', 'SCHEDULED'), 'OPEN'),
        'close_registration': (('OPEN',), 'REG_CLOSED'),
        'schedule': (('OPEN', 'REG_CLOSED'), 'SCHEDULED'),
        'cancel': (('DRAFT', 'OPEN', 'REG_CLOSED', 'SCHEDULED', 'READY_TO_START'), 'CANCELLED'),
    }

    def get_organisation(self):
        try:
            return self.request.user.organisation
        except Organisation.DoesNotExist as exc:
            raise PermissionDenied("Only organisation accounts can manage tournaments.") from exc

    @transaction.atomic
    def post(self, request, id):
        organisation = self.get_organisation()
        action = str(request.data.get('action', '')).strip()
        if action not in self.TRANSITIONS:
            return Response(
                {'detail': f"Unknown action. Use one of: {', '.join(self.TRANSITIONS)}."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        allowed_from, new_status = self.TRANSITIONS[action]

        tournament = get_object_or_404(
            Tournament.objects.select_for_update(),
            id=id,
            organisation=organisation,
        )
        if tournament.status not in allowed_from:
            return Response(
                {'detail': f"Cannot '{action}' a tournament that is {tournament.get_status_display()}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if action == 'cancel':
            _refund_all_registrations(tournament, request=request)
            reverse_tournament_fee(tournament, refunded=True)

        tournament.status = new_status
        tournament.save(update_fields=['status'])

        try:
            from audit.utils import log_action
            log_action(
                action=f'tournament_{action}',
                user=request.user,
                details={
                    'tournament_id': tournament.id,
                    'tournament_name': tournament.name,
                    'organisation_id': organisation.id,
                    'new_status': new_status,
                },
                request=request,
            )
        except Exception:
            pass

        return Response(
            TournamentSerializer(tournament, context={'request': request}).data,
            status=status.HTTP_200_OK,
        )


class OrganisationTournamentExtendRegistrationView(APIView):
    """
    POST /api/organisations/tournaments/{id}/extend-registration/

    Extend (or set) a tournament's registration deadline without cancelling it.
    Body: {"registration_closes_at": "<ISO 8601 datetime>"}.

    Existing players, payments, registrations and all tournament data stay
    intact. A tournament whose registration has closed (auto-closed on the
    deadline, manually closed, or scheduled) is re-opened so more players can
    join the SAME tournament. Can be used multiple times.
    """
    permission_classes = [permissions.IsAuthenticated]

    # Registration can be extended only while play hasn't started.
    EXTENDABLE_FROM = ('DRAFT', 'OPEN', 'REG_CLOSED', 'SCHEDULED')
    # Statuses where extending should re-open registration on the same tournament.
    REOPEN_FROM = ('REG_CLOSED', 'SCHEDULED')

    def get_organisation(self):
        try:
            return self.request.user.organisation
        except Organisation.DoesNotExist as exc:
            raise PermissionDenied("Only organisation accounts can manage tournaments.") from exc

    @transaction.atomic
    def post(self, request, id):
        from django.utils.dateparse import parse_datetime, parse_date
        import datetime as _dt

        organisation = self.get_organisation()

        raw = request.data.get('registration_closes_at')
        if not raw:
            return Response(
                {'detail': "A new registration closing date/time is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        new_deadline = parse_datetime(str(raw))
        if new_deadline is None:
            # Accept a date-only value; treat it as end of that day.
            parsed_date = parse_date(str(raw))
            if parsed_date is not None:
                new_deadline = _dt.datetime.combine(parsed_date, _dt.time(23, 59))
        if new_deadline is None:
            return Response(
                {'detail': "Invalid date/time. Use an ISO 8601 date or datetime."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if timezone.is_naive(new_deadline):
            new_deadline = timezone.make_aware(new_deadline, timezone.get_current_timezone())
        if new_deadline <= timezone.now():
            return Response(
                {'detail': "The new registration deadline must be in the future."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        tournament = get_object_or_404(
            Tournament.objects.select_for_update(),
            id=id,
            organisation=organisation,
        )
        if tournament.status not in self.EXTENDABLE_FROM:
            return Response(
                {'detail': f"Cannot extend registration for a tournament that is {tournament.get_status_display()}."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if tournament.registration_opens_at and new_deadline <= tournament.registration_opens_at:
            return Response(
                {'detail': "The registration deadline must be after registration opens."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        previous_deadline = tournament.registration_closes_at
        previous_status = tournament.status

        tournament.registration_closes_at = new_deadline
        update_fields = ['registration_closes_at', 'updated_at']
        if tournament.status in self.REOPEN_FROM:
            tournament.status = 'OPEN'
            update_fields.append('status')
        tournament.save(update_fields=update_fields)

        try:
            from audit.utils import log_action
            log_action(
                action='tournament_extend_registration',
                user=request.user,
                details={
                    'tournament_id': tournament.id,
                    'tournament_name': tournament.name,
                    'organisation_id': organisation.id,
                    'previous_deadline': previous_deadline.isoformat() if previous_deadline else None,
                    'new_deadline': new_deadline.isoformat(),
                    'previous_status': previous_status,
                    'new_status': tournament.status,
                },
                request=request,
            )
        except Exception:
            pass

        return Response(
            TournamentSerializer(tournament, context={'request': request}).data,
            status=status.HTTP_200_OK,
        )


class PlayerTournamentStandingsView(APIView):
    """
    GET /api/player/tournaments/{id}/standings/

    Standings visible to approved members of the tournament's organisation.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, id):
        tournament = get_object_or_404(Tournament.objects.select_related('organisation'), id=id)
        is_member = OrganisationMembership.objects.filter(
            organisation=tournament.organisation,
            player=request.user,
            status=OrganisationMembership.Status.APPROVED,
        ).exists()
        if not is_member:
            raise PermissionDenied("You must be an approved member to view these standings.")
        standings = tournament.standings.select_related('player', 'player__profile').all()
        return Response(TournamentStandingSerializer(standings, many=True).data)


def _bracket_queryset(tournament):
    from django.db.models import Prefetch
    return tournament.bracket_matches.select_related(
        'player1', 'player1__profile', 'player2', 'player2__profile',
        'winner', 'winner__profile', 'reported_winner', 'reported_winner__profile',
    ).prefetch_related(
        Prefetch('submissions', queryset=TournamentMatchSubmission.objects.select_related('player', 'player__profile', 'winner', 'winner__profile')),
    ).order_by('round_number', 'slot_number')


class OrganisationTournamentBracketView(APIView):
    """
    GET  /api/organisations/tournaments/{id}/bracket/   — view the bracket
    POST /api/organisations/tournaments/{id}/bracket/   — generate the bracket

    Generating closes registration (tournament → LIVE) and pairs players
    into a single-elimination bracket with byes.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get_organisation(self):
        try:
            return self.request.user.organisation
        except Organisation.DoesNotExist as exc:
            raise PermissionDenied("Only organisation accounts can manage brackets.") from exc

    def get_tournament(self, id):
        return get_object_or_404(Tournament, id=id, organisation=self.get_organisation())

    def get(self, request, id):
        tournament = self.get_tournament(id)
        matches = _bracket_queryset(tournament)
        return Response(TournamentMatchSerializer(matches, many=True, context={"request": request}).data)

    @transaction.atomic
    def post(self, request, id):
        tournament = get_object_or_404(
            Tournament.objects.select_for_update(),
            id=id,
            organisation=self.get_organisation(),
        )
        if tournament.status not in Tournament.PRE_PLAY_STATUSES:
            return Response(
                {'detail': 'Fixtures can only be generated before the tournament goes live.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if tournament.registered_players_count < tournament.max_players:
            return Response(
                {'detail': 'All tournament slots must be filled before it can start.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            settlement = confirm_full_tournament(tournament)
            if settlement is None:
                return Response(
                    {'detail': 'All tournament slots must be filled before it can start.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if tournament.format == 'LEAGUE':
                leagues.generate_league(tournament)
            else:
                brackets.generate_bracket(tournament)
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        tournament.status = 'LIVE'
        tournament.save(update_fields=['status'])
        recognize_tournament_fee(tournament)

        try:
            from audit.utils import log_action
            log_action(
                action='tournament_bracket_generated',
                user=request.user,
                details={
                    'tournament_id': tournament.id,
                    'tournament_name': tournament.name,
                    'organisation_id': tournament.organisation_id,
                    'players': tournament.registered_players_count,
                },
                request=request,
            )
        except Exception:
            pass

        # Notify + email every registered player that play has begun.
        from alert.notify import notify
        kind = 'fixtures' if tournament.format == 'LEAGUE' else 'bracket'
        registrations = TournamentRegistration.objects.select_related('player').filter(
            tournament=tournament,
            status=TournamentRegistration.Status.REGISTERED,
        )
        for reg in registrations:
            notify(
                reg.player,
                f"'{tournament.name}' has started — the {kind} is ready. Head to the tournament to play your matches.",
                link='/tournaments',
                email=True,
                subject=f"{tournament.name} has started",
            )

        matches = _bracket_queryset(tournament)
        return Response(
            TournamentMatchSerializer(matches, many=True, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


class OrganisationTournamentManualMatchView(APIView):
    """
    POST /api/organisations/tournaments/{id}/matches/

    Manually create a fixture the organiser controls, rather than relying only
    on the auto-generated bracket/fixtures. The organiser selects Player 1 and
    Player 2 (both must be registered) and may record the result immediately
    (scores + winner). The result is recorded against this tournament and these
    players; for leagues the live table/standings are rebuilt automatically.

    Body: {"player1_id", "player2_id", "player1_score"?, "player2_score"?}.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get_organisation(self):
        try:
            return self.request.user.organisation
        except Organisation.DoesNotExist as exc:
            raise PermissionDenied("Only organisation accounts can manage fixtures.") from exc

    @staticmethod
    def _parse_score(raw):
        try:
            value = int(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError("Scores must be whole numbers.") from exc
        if value < 0:
            raise ValueError("Scores cannot be negative.")
        return value

    @transaction.atomic
    def post(self, request, id):
        organisation = self.get_organisation()
        tournament = get_object_or_404(
            Tournament.objects.select_for_update(),
            id=id,
            organisation=organisation,
        )
        if tournament.status in Tournament.TERMINAL_STATUSES:
            return Response(
                {'detail': f"Cannot add fixtures to a tournament that is {tournament.get_status_display()}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            player1_id = int(request.data.get('player1_id'))
            player2_id = int(request.data.get('player2_id'))
        except (TypeError, ValueError):
            return Response(
                {'detail': 'Select both Player 1 and Player 2.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if player1_id == player2_id:
            return Response(
                {'detail': 'A fixture needs two different players.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        registered_ids = set(
            TournamentRegistration.objects.filter(
                tournament=tournament,
                status=TournamentRegistration.Status.REGISTERED,
                player_id__in=[player1_id, player2_id],
            ).values_list('player_id', flat=True)
        )
        if player1_id not in registered_ids or player2_id not in registered_ids:
            return Response(
                {'detail': 'Both players must be registered for this tournament.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Optional immediate result.
        raw_s1 = request.data.get('player1_score')
        raw_s2 = request.data.get('player2_score')
        has_result = raw_s1 is not None and raw_s2 is not None and raw_s1 != '' and raw_s2 != ''
        s1 = s2 = None
        if has_result:
            try:
                s1 = self._parse_score(raw_s1)
                s2 = self._parse_score(raw_s2)
            except ValueError as exc:
                return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        # Place manual fixtures on their own matchday after any existing rounds.
        last_round = tournament.bracket_matches.aggregate(
            m=Max('round_number')
        )['m'] or 0
        round_number = last_round + 1

        winner_id = None
        match_status = TournamentMatch.Status.READY
        if has_result:
            if s1 > s2:
                winner_id = player1_id
            elif s2 > s1:
                winner_id = player2_id
            match_status = TournamentMatch.Status.CONFIRMED

        match = TournamentMatch.objects.create(
            tournament=tournament,
            round_number=round_number,
            slot_number=0,
            player1_id=player1_id,
            player2_id=player2_id,
            player1_score=s1,
            player2_score=s2,
            winner_id=winner_id,
            status=match_status,
        )

        # Manually managing fixtures starts play if the tournament hadn't yet.
        if tournament.status in ('OPEN', 'REG_CLOSED', 'SCHEDULED'):
            tournament.status = 'LIVE'
            tournament.save(update_fields=['status'])

        # A recorded league result feeds the live table/standings.
        if has_result and tournament.format == 'LEAGUE':
            leagues.rebuild_league_standings(tournament)

        try:
            from audit.utils import log_action
            log_action(
                action='tournament_manual_fixture',
                user=request.user,
                details={
                    'tournament_id': tournament.id,
                    'tournament_name': tournament.name,
                    'organisation_id': organisation.id,
                    'match_id': match.id,
                    'player1_id': player1_id,
                    'player2_id': player2_id,
                    'player1_score': s1,
                    'player2_score': s2,
                    'winner_id': winner_id,
                    'recorded_result': has_result,
                },
                request=request,
            )
        except Exception:
            pass

        matches = _bracket_queryset(tournament)
        return Response(
            {
                'match': TournamentMatchSerializer(match, context={'request': request}).data,
                'bracket': TournamentMatchSerializer(matches, many=True, context={'request': request}).data,
            },
            status=status.HTTP_201_CREATED,
        )


class OrganisationTournamentMatchConfirmView(APIView):
    """
    POST /api/organisations/tournaments/{id}/matches/{match_id}/confirm/

    Confirm (or correct) a bracket match result and advance the winner. Body may
    include {"winner_id"} to override the player-reported winner. Confirming the
    final rebuilds the tournament's final standings automatically.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get_organisation(self):
        try:
            return self.request.user.organisation
        except Organisation.DoesNotExist as exc:
            raise PermissionDenied("Only organisation accounts can confirm results.") from exc

    def post(self, request, id, match_id):
        tournament = get_object_or_404(Tournament, id=id, organisation=self.get_organisation())
        match = get_object_or_404(TournamentMatch, id=match_id, tournament=tournament)
        try:
            if tournament.format == 'LEAGUE':
                match = leagues.confirm_score(
                    tournament, match,
                    s1=request.data.get('player1_score'),
                    s2=request.data.get('player2_score'),
                )
                remaining = tournament.bracket_matches.exclude(
                    status=TournamentMatch.Status.CONFIRMED
                ).exists()
                is_final = not remaining
            else:
                match, is_final = brackets.confirm_result(
                    match, winner_id=request.data.get('winner_id'),
                )
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        if tournament.format != 'LEAGUE':
            from alert.notify import notify
            for player in (match.player1, match.player2):
                if player:
                    won = player.id == match.winner_id
                    notify(
                        player,
                        (
                            f"Your match in '{tournament.name}' is confirmed — "
                            f"{'you advanced!' if won else 'you were eliminated.'}"
                        ),
                        link='/tournaments',
                    )

        matches = _bracket_queryset(tournament)
        return Response(
            {
                'final': is_final,
                'bracket': TournamentMatchSerializer(matches, many=True, context={"request": request}).data,
            },
            status=status.HTTP_200_OK,
        )


class PlayerTournamentBracketView(APIView):
    """
    GET /api/player/tournaments/{id}/bracket/

    Bracket visible to approved members of the tournament's organisation.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, id):
        tournament = get_object_or_404(Tournament.objects.select_related('organisation'), id=id)
        is_member = OrganisationMembership.objects.filter(
            organisation=tournament.organisation,
            player=request.user,
            status=OrganisationMembership.Status.APPROVED,
        ).exists()
        if not is_member:
            raise PermissionDenied("You must be an approved member to view this bracket.")
        matches = _bracket_queryset(tournament)
        return Response(TournamentMatchSerializer(matches, many=True, context={"request": request}).data)


class PlayerTournamentMatchReportView(APIView):
    """
    POST /api/player/tournaments/{id}/matches/{match_id}/report/

    A participant submits their result (both players submit; agreement
    auto-confirms, disagreement goes to the organiser). Accepts multipart with
    an optional ``evidence`` screenshot.
    Knockout body: {"winner_id"}. League body: {"player1_score","player2_score"}.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, id, match_id):
        from matches import results
        from alert.notify import notify

        tournament = get_object_or_404(Tournament, id=id)
        match = get_object_or_404(TournamentMatch, id=match_id, tournament=tournament)

        winner_id = request.data.get('winner_id')
        if winner_id is not None:
            try:
                winner_id = int(winner_id)
            except (TypeError, ValueError):
                return Response({'detail': 'winner_id must be a player id.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            match, outcome = results.submit_result(
                tournament,
                match,
                player_id=request.user.id,
                winner_id=winner_id,
                s1=request.data.get('player1_score'),
                s2=request.data.get('player2_score'),
                evidence=request.FILES.get('evidence'),
            )
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        # Notify the relevant people based on how the submission resolved.
        opponent = match.player2 if request.user.id == match.player1_id else match.player1
        if outcome == results.AWAITING_OPPONENT and opponent:
            notify(
                opponent,
                f"Your opponent submitted a result for your match in '{tournament.name}'. Please submit yours to confirm it.",
                link='/tournaments', email=True,
                subject=f"Submit your result — {tournament.name}",
            )
        elif outcome == results.CONFIRMED:
            for player in (match.player1, match.player2):
                if player:
                    won = player.id == match.winner_id
                    notify(
                        player,
                        f"Your match result in '{tournament.name}' is confirmed — "
                        + ("it's a draw." if match.winner_id is None and tournament.format == 'LEAGUE'
                           else ("you advanced!" if won else "you were eliminated.")),
                        link='/tournaments',
                    )
        elif outcome == results.DISPUTED:
            for player in (match.player1, match.player2):
                if player:
                    notify(
                        player,
                        f"Your submitted results for a match in '{tournament.name}' don't match. The organiser will review and confirm.",
                        link='/tournaments', email=True,
                        subject=f"Result needs review — {tournament.name}",
                    )
            # Nudge the organiser too.
            org_user = getattr(tournament.organisation, 'user', None) or getattr(tournament.organisation, 'owner', None)
            if org_user:
                notify(
                    org_user,
                    f"A match in '{tournament.name}' has conflicting player results and needs your decision.",
                    link='/organiser/dashboard',
                )

        matches = _bracket_queryset(tournament)
        return Response(TournamentMatchSerializer(matches, many=True, context={"request": request}).data, status=status.HTTP_200_OK)


def _enriched_league_table(tournament):
    from api.serializers import tournament_team_map
    table = leagues.compute_table(tournament)
    ids = [r['player_id'] for r in table]
    users = {u.id: u for u in CustomUser.objects.filter(id__in=ids).select_related('profile')}
    team_map = tournament_team_map(tournament)
    rows = []
    for position, r in enumerate(table, start=1):
        user = users.get(r['player_id'])
        name = user.username if user else str(r['player_id'])
        if user:
            profile = getattr(user, 'profile', None)
            if profile:
                full = f"{profile.first_name} {profile.last_name}".strip()
                if full:
                    name = full
        team = team_map.get(r['player_id'])
        if team:
            name = f"{name} ({team})"
        rows.append({
            'position': position,
            'player_id': r['player_id'],
            'player_username': user.username if user else '',
            'player_name': name,
            'team_name': team or None,
            'played': r['played'],
            'won': r['won'],
            'drawn': r['drawn'],
            'lost': r['lost'],
            'gf': r['gf'],
            'ga': r['ga'],
            'gd': r['gd'],
            'points': r['points'],
        })
    return rows


class OrganisationTournamentTableView(APIView):
    """GET /api/organisations/tournaments/{id}/table/ — live league table."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, id):
        try:
            organisation = request.user.organisation
        except Organisation.DoesNotExist as exc:
            raise PermissionDenied("Only organisation accounts can view this table.") from exc
        tournament = get_object_or_404(Tournament, id=id, organisation=organisation)
        return Response(_enriched_league_table(tournament))


class PlayerTournamentTableView(APIView):
    """GET /api/player/tournaments/{id}/table/ — live league table for members."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, id):
        tournament = get_object_or_404(Tournament.objects.select_related('organisation'), id=id)
        is_member = OrganisationMembership.objects.filter(
            organisation=tournament.organisation,
            player=request.user,
            status=OrganisationMembership.Status.APPROVED,
        ).exists()
        if not is_member:
            raise PermissionDenied("You must be an approved member to view this table.")
        return Response(_enriched_league_table(tournament))


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


class OrganisationWalletDetailView(generics.RetrieveAPIView):
    """
    GET /api/organisations/wallet/

    Return the authenticated organisation owner's wallet balance.
    """
    serializer_class = OrganisationWalletSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        organisation = get_object_or_404(Organisation, owner=self.request.user)
        wallet, _created = OrganisationWallet.objects.select_related('organisation').get_or_create(
            organisation=organisation
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


class OrganisationTransactionHistoryView(generics.ListAPIView):
    """
    GET /api/organisations/wallet/transactions/

    Return the authenticated organisation owner's wallet transaction history.
    """
    serializer_class = OrganisationTransactionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        organisation = get_object_or_404(Organisation, owner=self.request.user)
        return (
            OrganisationTransaction.objects.select_related('wallet', 'related_match')
            .filter(wallet__organisation=organisation)
            .order_by('-created_at')
        )


class OrganisationDepositCreateView(APIView):
    """Create a deposit that is credited only to the authenticated owner's organisation wallet."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        organisation = get_object_or_404(Organisation, owner=request.user)
        serializer = DepositCreateSerializer(
            data=request.data,
            context={'request': request, 'organisation': organisation},
        )
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        deposit = serializer.save()
        from wallet.utils import initialize_deposit_payment

        payment = initialize_deposit_payment(
            deposit,
            request,
            mobile_number=serializer.validated_data.get('mobile_number'),
        )
        from wallet.utils import get_deposit_payment_status_payload
        from audit.utils import log_action

        log_action(
            action='organisation_deposit_created',
            user=request.user,
            details={
                'organisation_id': organisation.id,
                'deposit_id': deposit.id,
                'amount': str(deposit.amount),
                'payment_method': deposit.payment_method,
                'status': deposit.status,
                'payment_initialized': payment.get('initialized'),
            },
            request=request,
        )

        payload = {
            **get_deposit_payment_status_payload(deposit),
            'message': payment['message'],
        }
        if payment.get('payment_url'):
            payload['payment_url'] = payment['payment_url']
        if payment.get('failure_reason'):
            payload['failure_reason'] = payment['failure_reason']
        return Response(
            payload,
            status=status.HTTP_201_CREATED if payment['success'] else status.HTTP_400_BAD_REQUEST,
        )


class OrganisationPaymentStatusView(APIView):
    """Poll only deposits belonging to the authenticated owner's organisation wallet."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, order_id):
        from wallet.models import Deposit
        from wallet.utils import get_deposit_payment_status_payload, refresh_deposit_payment_status

        organisation = get_object_or_404(Organisation, owner=request.user)
        deposit = get_object_or_404(
            Deposit,
            id=order_id,
            organisation_wallet__organisation=organisation,
        )
        deposit = refresh_deposit_payment_status(deposit)
        return Response(get_deposit_payment_status_payload(deposit))


class OrganisationWithdrawalListView(generics.ListAPIView):
    """List withdrawals from only the authenticated owner's organisation wallet."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = WithdrawalSerializer

    def get_queryset(self):
        organisation = get_object_or_404(Organisation, owner=self.request.user)
        return Withdrawal.objects.filter(
            organisation_wallet__organisation=organisation,
        ).order_by('-created_at')


class OrganisationWithdrawalCreateView(APIView):
    """Create and process a payout from the authenticated owner's organisation wallet."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        organisation = get_object_or_404(Organisation, owner=request.user)
        serializer = WithdrawalCreateSerializer(
            data=request.data,
            context={'request': request, 'organisation': organisation},
        )
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        withdrawal = serializer.save()
        from audit.utils import log_action

        log_action(
            action='organisation_withdrawal_created',
            user=request.user,
            details={
                'organisation_id': organisation.id,
                'withdrawal_id': withdrawal.id,
                'amount': str(withdrawal.amount),
                'payment_method': withdrawal.payment_method,
                'status': withdrawal.status,
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
        from wallet.utils import get_deposit_payment_status_payload, refresh_deposit_payment_status

        deposit = get_object_or_404(Deposit, id=order_id, user=request.user)
        deposit = refresh_deposit_payment_status(deposit)

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

        raw_body = request.body or b''
        logger.info(
            'Zynle webhook HTTP hit: path=%s content_type=%s remote_addr=%s user_agent=%s bytes=%s body=%s',
            request.path,
            request.META.get('CONTENT_TYPE', ''),
            request.META.get('REMOTE_ADDR', ''),
            request.META.get('HTTP_USER_AGENT', ''),
            len(raw_body),
            raw_body.decode('utf-8', errors='replace')[:2000],
        )
        result = get_payment_gateway('zynle').handle_webhook(request)
        logger.info(
            'Zynle webhook handled: processed=%s deposit_id=%s withdrawal_id=%s payment_status=%s message=%s',
            result.processed,
            result.deposit_id,
            result.withdrawal_id,
            result.payment_status,
            result.message,
        )
        if not result.processed and 'token' in (result.message or '').lower():
            return Response(
                {'status': 'error', 'message': result.message},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        raw_payload = result.raw_payload or {}
        payload = raw_payload.get('response') if isinstance(raw_payload.get('response'), dict) else raw_payload
        reference_no = ''
        if isinstance(payload, dict):
            reference_no = str(payload.get('reference_no') or payload.get('referenceNo') or '').strip()
        if result.processed:
            return Response({
                'response_code': '130',
                'reference_no': reference_no,
            })
        return Response({
            'status': 'ok' if result.processed else 'ignored',
            'message': result.message,
            'deposit_id': result.deposit_id,
            'withdrawal_id': result.withdrawal_id,
            'payment_status': result.payment_status,
        })


class WithdrawalListView(generics.ListAPIView):
    """
    GET /api/wallet/withdrawals/

    The authenticated user's withdrawal requests, newest first, with their
    current status (Pending / Processing / Completed / Failed / Cancelled),
    payout reference and any failure reason.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = WithdrawalSerializer

    def get_queryset(self):
        return Withdrawal.objects.filter(user=self.request.user).order_by('-created_at')


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
    
    @action(detail=True, methods=['post'], url_path='mark-read')
    def mark_read(self, request, pk=None):
        """
        POST /api/notifications/{id}/mark-read/
        
        Mark a specific notification as read.
        """
        notification = get_object_or_404(Notification, pk=pk)
        
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
    
    @action(detail=False, methods=['post'], url_path='mark-all-read')
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
    
    @action(detail=False, methods=['get'], url_path='unread-count')
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


class LeaderboardView(APIView):
    """
    GET /api/leaderboard/?game=&ordering=

    Public, privacy-safe leaderboard of players ranked by game performance.
    Optional `game` filter; `ordering` in {won, win_rate, winnings, played}.
    Exposes only competitive stats (no deposits, withdrawals or balances).
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from django.db.models import Sum
        from collections import defaultdict
        from wallet.models import Transaction

        game = (request.query_params.get('game') or '').strip()
        ordering = request.query_params.get('ordering') or 'won'
        if ordering not in ('won', 'win_rate', 'winnings', 'played'):
            ordering = 'won'

        matches_qs = Match.objects.filter(status__in=['JOINED', 'COMPLETED', 'DISPUTED'])
        if game:
            matches_qs = matches_qs.filter(game=game)

        draw_ids = set(
            Transaction.objects.filter(transaction_type='MATCH_DRAW_RETURN', related_match__isnull=False)
            .values_list('related_match_id', flat=True)
        )

        rec = defaultdict(lambda: {'played': 0, 'won': 0, 'lost': 0, 'draw': 0})
        for m in matches_qs.values('id', 'creator_id', 'joiner_id', 'winner_id'):
            participants = [p for p in (m['creator_id'], m['joiner_id']) if p]
            for p in participants:
                rec[p]['played'] += 1
            if m['id'] in draw_ids:
                for p in participants:
                    rec[p]['draw'] += 1
            elif m['winner_id']:
                rec[m['winner_id']]['won'] += 1
                for p in participants:
                    if p != m['winner_id']:
                        rec[p]['lost'] += 1

        win_qs = Transaction.objects.filter(transaction_type='MATCH_WINNINGS')
        if game:
            win_qs = win_qs.filter(related_match__game=game)
        winnings = {
            r['wallet__user']: r['s'] or 0
            for r in win_qs.values('wallet__user').annotate(s=Sum('amount'))
        }

        usernames = dict(User.objects.values_list('id', 'username'))

        rows = []
        for uid, r in rec.items():
            if r['played'] == 0:
                continue
            decided = r['won'] + r['lost'] + r['draw']
            rows.append({
                'user_id': uid,
                'username': usernames.get(uid, f'#{uid}'),
                'played': r['played'],
                'won': r['won'],
                'lost': r['lost'],
                'draw': r['draw'],
                'win_rate': round(100 * r['won'] / decided, 1) if decided else 0.0,
                'winnings': str(winnings.get(uid, 0)),
            })

        rows.sort(key=lambda x: float(x[ordering]), reverse=True)
        for i, row in enumerate(rows):
            row['rank'] = i + 1

        me = next((r for r in rows if r['user_id'] == request.user.id), None)

        return Response({'results': rows[:100], 'me': me, 'game': game or None, 'ordering': ordering})
