from __future__ import annotations

from decimal import Decimal

import strawberry
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.db import transaction
from django.template.loader import render_to_string
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.utils import timezone
from graphql import GraphQLError
from rest_framework_simplejwt.serializers import (
    TokenObtainPairSerializer,
    TokenRefreshSerializer,
    TokenVerifySerializer,
)
from rest_framework_simplejwt.tokens import RefreshToken, UntypedToken
from rest_framework_simplejwt.exceptions import TokenError

from alert.models import Notification, ReadNotification
from api.serializers import (
    ChangePasswordSerializer,
    DepositCreateSerializer,
    DisputeResolutionSerializer,
    MatchCreateSerializer,
    MatchJoinSerializer,
    MatchResultSubmissionSerializer,
    MessageCreateSerializer,
    ProfileSerializer,
    UserRegistrationSerializer,
    UserUpdateSerializer,
    WithdrawalCreateSerializer,
)
from matches.models import Match, MatchResult
from messenger.models import Message, ReadMessage
from panel.models import Dispute
from wallet.models import Transaction, Wallet
from wallet.notifications import notify_withdrawal_created
from wallet.withdrawal_processing import process_withdrawal_now

from .types import (
    AuthPayload,
    DepositStatusType,
    DisputeType,
    MatchPayload,
    MeType,
    MessagePayload,
    MessageType,
    NotificationType,
    TokenPayload,
    TokenVerificationPayload,
    WalletType,
    WithdrawalPayload,
)
from .utils import (
    enforce_graphql_rate_limit,
    require_authenticated_user,
    serializer_error,
    validation_error,
)

User = get_user_model()


@strawberry.type
class Mutation:
    @strawberry.mutation
    def register(
        self,
        info: strawberry.Info,
        username: str,
        email: str,
        password: str,
        password_confirm: str,
    ) -> AuthPayload:
        enforce_graphql_rate_limit(info, "register", email)
        serializer = UserRegistrationSerializer(data={
            "username": username,
            "email": email,
            "password": password,
            "password_confirm": password_confirm,
        })
        if not serializer.is_valid():
            serializer_error(serializer)

        user = serializer.save()
        refresh = RefreshToken.for_user(user)
        return AuthPayload(user=user, access=str(refresh.access_token), refresh=str(refresh))

    @strawberry.mutation
    def token_auth(self, info: strawberry.Info, username: str, password: str) -> TokenPayload:
        enforce_graphql_rate_limit(info, "token_auth", username)
        serializer = TokenObtainPairSerializer(data={"username": username, "password": password})
        if not serializer.is_valid():
            serializer_error(serializer)
        return TokenPayload(
            access=serializer.validated_data["access"],
            refresh=serializer.validated_data["refresh"],
        )

    @strawberry.mutation
    def refresh_token(self, info: strawberry.Info, refresh: str) -> TokenPayload:
        serializer = TokenRefreshSerializer(data={"refresh": refresh})
        if not serializer.is_valid():
            serializer_error(serializer)
        return TokenPayload(
            access=serializer.validated_data["access"],
            refresh=serializer.validated_data.get("refresh"),
        )

    @strawberry.mutation
    def verify_token(self, info: strawberry.Info, token: str) -> TokenVerificationPayload:
        enforce_graphql_rate_limit(info, "verify_token")
        serializer = TokenVerifySerializer(data={"token": token})
        if not serializer.is_valid():
            return TokenVerificationPayload(valid=False)
        try:
            validated = UntypedToken(token)
        except TokenError:
            return TokenVerificationPayload(valid=False)
        return TokenVerificationPayload(
            valid=True,
            token_type=validated.payload.get("token_type"),
            user_id=validated.payload.get("user_id"),
            expires_at=validated.payload.get("exp"),
        )

    @strawberry.mutation
    def logout(self, info: strawberry.Info, refresh: str) -> MessagePayload:
        require_authenticated_user(info)
        enforce_graphql_rate_limit(info, "logout")
        try:
            token = RefreshToken(refresh)
            token.blacklist()
        except TokenError:
            validation_error("Invalid refresh token.")
        return MessagePayload(message="Logged out successfully.")

    @strawberry.mutation
    def change_password(
        self,
        info: strawberry.Info,
        old_password: str,
        new_password: str,
        new_password_confirm: str,
    ) -> MessagePayload:
        require_authenticated_user(info)
        enforce_graphql_rate_limit(info, "change_password")
        serializer = ChangePasswordSerializer(
            data={
                "old_password": old_password,
                "new_password": new_password,
                "new_password_confirm": new_password_confirm,
            },
            context={"request": info.context.request},
        )
        if not serializer.is_valid():
            serializer_error(serializer)
        serializer.save()
        return MessagePayload(message="Password changed successfully")

    @strawberry.mutation
    def request_password_reset(self, info: strawberry.Info, email: str) -> MessagePayload:
        enforce_graphql_rate_limit(info, "password_reset", email)
        if not email:
            validation_error("Email is required")
        request = info.context.request
        users = User.objects.filter(email__iexact=email, is_active=True)
        for user in users:
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            reset_path = f"/accounts/reset/{uid}/{token}/"
            context = {
                "email": user.email,
                "domain": request.get_host(),
                "site_name": "PlayArena",
                "uid": uid,
                "user": user,
                "token": token,
                "protocol": "https" if request.is_secure() else "http",
            }
            html_body = render_to_string("registration/password_reset_email.html", context)
            text_body = render_to_string("registration/password_reset_email.html", context)
            user.email_user(
                "Reset Your PlayArena Password",
                text_body,
                settings.DEFAULT_FROM_EMAIL,
                html_message=html_body,
            )
        return MessagePayload(
            message="If an account exists with this email, a password reset link has been sent."
        )

    @strawberry.mutation
    def reset_password_confirm(
        self,
        info: strawberry.Info,
        uid: str,
        token: str,
        new_password: str,
        new_password_confirm: str,
    ) -> MessagePayload:
        enforce_graphql_rate_limit(info, "password_reset_confirm", uid)
        if new_password != new_password_confirm:
            validation_error({"new_password_confirm": "Password fields didn't match."})

        try:
            user_id = force_str(urlsafe_base64_decode(uid))
            user = User.objects.get(pk=user_id, is_active=True)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            validation_error("Invalid or expired password reset link.")

        if not default_token_generator.check_token(user, token):
            validation_error("Invalid or expired password reset link.")

        try:
            validate_password(new_password, user)
        except Exception as exc:
            validation_error(getattr(exc, "messages", str(exc)))

        user.set_password(new_password)
        user.save(update_fields=["password"])
        return MessagePayload(message="Password has been reset successfully.")

    @strawberry.mutation
    def update_me(
        self,
        info: strawberry.Info,
        username: str | None = None,
        email: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
    ) -> MeType:
        user = require_authenticated_user(info)
        data = _compact({
            "username": username,
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
        })
        serializer = UserUpdateSerializer(user, data=data, partial=True)
        if not serializer.is_valid():
            serializer_error(serializer)
        return serializer.save()

    @strawberry.mutation
    def update_profile(
        self,
        info: strawberry.Info,
        first_name: str | None = None,
        last_name: str | None = None,
    ) -> MeType:
        user = require_authenticated_user(info)
        profile, _created = user.profile.__class__.objects.get_or_create(user=user)
        serializer = ProfileSerializer(
            profile,
            data=_compact({"first_name": first_name, "last_name": last_name}),
            partial=True,
        )
        if not serializer.is_valid():
            serializer_error(serializer)
        serializer.save()
        return User.objects.select_related("profile").get(pk=user.pk)

    @strawberry.mutation
    @transaction.atomic
    def create_match(
        self,
        info: strawberry.Info,
        game: str,
        device: str,
        privacy: str,
        amount: int,
    ) -> MatchPayload:
        user = require_authenticated_user(info)
        request = info.context.request
        serializer = MatchCreateSerializer(
            data={"game": game, "device": device, "privacy": privacy, "amount": amount},
            context={"request": request},
        )
        if not serializer.is_valid():
            serializer_error(serializer)

        match = Match(**serializer.validated_data)
        match.creator = user
        match.save()

        wallet, _created = Wallet.objects.get_or_create(user=user)
        stake = Decimal(match.amount)
        wallet.balance -= stake
        wallet.save(update_fields=["balance"])

        Transaction.objects.create(
            wallet=wallet,
            amount=-stake,
            transaction_type="MATCH_CREATION",
            description=f"Created {match.get_game_display()} match for ZMW {match.amount}",
            related_match=match,
        )
        return MatchPayload(message="Match created successfully.", match=match, status=match.status)

    @strawberry.mutation
    @transaction.atomic
    def join_match(self, info: strawberry.Info, joining_code: str) -> MatchPayload:
        user = require_authenticated_user(info)
        serializer = MatchJoinSerializer(
            data={"joining_code": joining_code},
            context={"request": info.context.request},
        )
        if not serializer.is_valid():
            serializer_error(serializer)

        match = Match.objects.select_for_update().get(pk=serializer.context["match"].pk)
        if match.status != "OPEN" or match.joiner is not None:
            validation_error("Match is no longer available.")
        if match.creator == user:
            validation_error("You cannot join your own match.")

        wallet, _created = Wallet.objects.get_or_create(user=user)
        if wallet.balance < Decimal(match.amount):
            validation_error(f"Insufficient funds. You need ZMW {match.amount} to join this match.")

        match.joiner = user
        match.status = "JOINED"
        match.save(update_fields=["joiner", "status"])

        stake = Decimal(match.amount)
        wallet.balance -= stake
        wallet.save(update_fields=["balance"])
        Transaction.objects.create(
            wallet=wallet,
            amount=-stake,
            transaction_type="MATCH_JOINING",
            description=(
                f"Joined {match.get_game_display()} match against {match.creator.username} "
                f"for ZMW {match.amount}"
            ),
            related_match=match,
        )
        return MatchPayload(message="Match joined successfully.", match=match, status=match.status)

    @strawberry.mutation
    @transaction.atomic
    def submit_match_result(
        self,
        info: strawberry.Info,
        match_id: strawberry.ID,
        submission: str,
    ) -> MatchPayload:
        user = require_authenticated_user(info)
        match = _get_match(match_id)
        if user not in [match.creator, match.joiner]:
            validation_error("You are not a participant in this match.")
        if match.status != "JOINED":
            validation_error(
                f"Cannot submit result for a match with status '{match.get_status_display()}'."
            )

        serializer = MatchResultSubmissionSerializer(data={"submission": submission})
        if not serializer.is_valid():
            serializer_error(serializer)

        match_result, _created = MatchResult.objects.select_for_update().get_or_create(match=match)
        submission_value = serializer.validated_data["submission"]
        is_creator = user == match.creator

        if is_creator:
            if match_result.creator_submission:
                validation_error("You have already submitted your result for this match.")
            match_result.creator_submission = submission_value
            match_result.creator_submission_time = timezone.now()
        else:
            if match_result.joiner_submission:
                validation_error("You have already submitted your result for this match.")
            match_result.joiner_submission = submission_value
            match_result.joiner_submission_time = timezone.now()
        match_result.save()

        if not match_result.creator_submission or not match_result.joiner_submission:
            opponent = match.joiner if is_creator else match.creator
            Notification.objects.create(
                user=opponent,
                message=(
                    f"Your opponent has submitted their result for the {match.get_game_display()} "
                    f"match (ZMW {match.amount}). Please submit your result."
                ),
            )
            return MatchPayload(message="Result submitted. Waiting for opponent.", match=match)

        return _resolve_submitted_match_result(match, match_result)

    @strawberry.mutation
    @transaction.atomic
    def cancel_match(self, info: strawberry.Info, match_id: strawberry.ID) -> MatchPayload:
        user = require_authenticated_user(info)
        match = _get_match(match_id)
        if user not in [match.creator, match.joiner]:
            validation_error("You don't have permission to cancel this match.")
        if match.status == "JOINED":
            validation_error("Cannot cancel or leave a joined match. Both players must submit results first.")
        if match.status != "OPEN":
            validation_error(f"Cannot cancel a match with status '{match.get_status_display()}'.")

        result = MatchResult.objects.filter(match=match).first()
        if result and (result.creator_submission or result.joiner_submission):
            validation_error("This match can't be cancelled because a result has already been submitted.")

        match_game = match.get_game_display()
        match_amount = match.amount

        if user == match.creator:
            creator_wallet = match.creator.wallet
            creator_wallet.balance += Decimal(match.amount)
            creator_wallet.save(update_fields=["balance"])
            Transaction.objects.create(
                wallet=creator_wallet,
                amount=Decimal(match.amount),
                transaction_type="MATCH_REFUND",
                description=f"Refund from cancelled {match_game} match for ZMW {match_amount}",
                related_match=match,
            )
            if match.joiner:
                joiner_wallet = match.joiner.wallet
                joiner_wallet.balance += Decimal(match.amount)
                joiner_wallet.save(update_fields=["balance"])
                Transaction.objects.create(
                    wallet=joiner_wallet,
                    amount=Decimal(match.amount),
                    transaction_type="MATCH_REFUND",
                    description=f"Refund from cancelled {match_game} match for ZMW {match_amount}",
                    related_match=match,
                )
                Notification.objects.create(
                    user=match.joiner,
                    message=(
                        f"A {match_game} match you joined has been cancelled by the creator. "
                        f"ZMW {match_amount} has been refunded to your wallet."
                    ),
                )

            match.delete()
            return MatchPayload(message="Match cancelled and refunded.", status="CANCELLED")

        joiner_wallet = match.joiner.wallet
        joiner_wallet.balance += Decimal(match.amount)
        joiner_wallet.save(update_fields=["balance"])
        match.joiner = None
        match.status = "OPEN"
        match.save(update_fields=["joiner", "status"])
        Transaction.objects.create(
            wallet=joiner_wallet,
            amount=Decimal(match.amount),
            transaction_type="MATCH_REFUND",
            description=f"Refund from leaving {match_game} match for ZMW {match_amount}",
            related_match=match,
        )
        Notification.objects.create(
            user=match.creator,
            message=f"{user.username} has left your {match_game} match. The match is now open.",
        )
        return MatchPayload(message="You have left the match and been refunded.", match=match, status=match.status)

    @strawberry.mutation
    def create_deposit(
        self,
        info: strawberry.Info,
        amount: Decimal,
        payment_method: str,
        mobile_number: str | None = None,
    ) -> DepositStatusType:
        user = require_authenticated_user(info)
        request = info.context.request
        serializer = DepositCreateSerializer(
            data={
                "amount": amount,
                "payment_method": payment_method,
                "mobile_number": mobile_number or "",
            },
            context={"request": request},
        )
        if not serializer.is_valid():
            serializer_error(serializer)

        deposit = serializer.save()
        from wallet.utils import get_deposit_payment_status_payload, initialize_deposit_payment

        payment = initialize_deposit_payment(
            deposit,
            request,
            mobile_number=serializer.validated_data.get("mobile_number"),
        )
        payload = {
            **get_deposit_payment_status_payload(deposit),
            "message": payment["message"],
            "payment_url": payment.get("payment_url"),
        }
        if payment.get("failure_reason"):
            payload["failure_reason"] = payment["failure_reason"]
        return _deposit_status_from_payload(payload)

    @strawberry.mutation
    def create_withdrawal(
        self,
        info: strawberry.Info,
        amount: Decimal,
        payment_method: str,
        account_details: str,
    ) -> WithdrawalPayload:
        user = require_authenticated_user(info)
        request = info.context.request
        serializer = WithdrawalCreateSerializer(
            data={
                "amount": amount,
                "payment_method": payment_method,
                "account_details": account_details,
            },
            context={"request": request},
        )
        if not serializer.is_valid():
            serializer_error(serializer)

        withdrawal = serializer.save()
        notify_withdrawal_created(withdrawal)

        process_result = None
        if (
            withdrawal.payment_method == "MOBILE_MONEY"
            and getattr(settings, "WALLET_AUTO_PROCESS_WITHDRAWALS", True)
        ):
            process_result = process_withdrawal_now(withdrawal, actor=user)
            withdrawal.refresh_from_db()

        return WithdrawalPayload(
            withdrawal_id=withdrawal.id,
            status=withdrawal.status,
            amount=withdrawal.amount,
            payment_method=withdrawal.payment_method,
            transaction_id=withdrawal.transaction_id,
            gateway_transaction_id=withdrawal.gateway_transaction_id,
            message=(
                process_result.get("message")
                if process_result
                else "Withdrawal request created and queued for processing."
            ),
        )

    @strawberry.mutation
    def resolve_dispute(
        self,
        info: strawberry.Info,
        dispute_id: strawberry.ID,
        status: str,
        resolution_notes: str | None = "",
    ) -> DisputeType:
        user = require_authenticated_user(info)
        if not user.is_staff:
            validation_error("Only staff users can resolve disputes.")

        dispute = _get_dispute(dispute_id)
        serializer = DisputeResolutionSerializer(
            data={"status": status, "resolution_notes": resolution_notes or ""}
        )
        if not serializer.is_valid():
            serializer_error(serializer)

        dispute.status = serializer.validated_data["status"]
        dispute.resolution_notes = serializer.validated_data.get("resolution_notes", "")
        if dispute.status == "RESOLVED":
            dispute.resolved_at = timezone.now()
        dispute.save()

        participants = [dispute.match.creator]
        if dispute.match.joiner:
            participants.append(dispute.match.joiner)
        for participant in participants:
            Notification.objects.create(
                user=participant,
                message=(
                    f"Dispute for match {dispute.match.joining_code} has been "
                    f"{dispute.get_status_display().lower()}."
                ),
            )
        return dispute

    @strawberry.mutation
    def send_message(self, info: strawberry.Info, receiver_id: strawberry.ID, message: str) -> MessageType:
        user = require_authenticated_user(info)
        serializer = MessageCreateSerializer(
            data={"receiver": int(receiver_id), "message": message},
            context={"request": info.context.request},
        )
        if not serializer.is_valid():
            serializer_error(serializer)
        msg = serializer.save(sender=user)
        Notification.objects.create(
            user=serializer.validated_data["receiver"],
            message=f"You have a new message from {user.username}",
        )
        return msg

    @strawberry.mutation
    def mark_notification_read(
        self,
        info: strawberry.Info,
        notification_id: strawberry.ID,
    ) -> NotificationType:
        user = require_authenticated_user(info)
        notification = _get_notification(notification_id)
        if notification.user != user:
            validation_error("You can only mark your own notifications as read.")
        ReadNotification.objects.get_or_create(notification=notification, user=user)
        return notification

    @strawberry.mutation
    def mark_all_notifications_read(self, info: strawberry.Info) -> MessagePayload:
        user = require_authenticated_user(info)
        unread_notifications = Notification.objects.filter(user=user).exclude(
            id__in=ReadNotification.objects.filter(user=user).values_list("notification_id", flat=True)
        )
        count = unread_notifications.count()
        for notification in unread_notifications:
            ReadNotification.objects.get_or_create(notification=notification, user=user)
        return MessagePayload(message=f"{count} notifications marked as read.")


def _compact(data):
    return {key: value for key, value in data.items() if value is not None}


def _get_match(match_id):
    try:
        return Match.objects.select_related("creator", "joiner", "winner").get(id=int(match_id))
    except (Match.DoesNotExist, ValueError):
        raise GraphQLError("Match not found.")


def _get_dispute(dispute_id):
    try:
        return Dispute.objects.select_related(
            "match",
            "match__creator",
            "match__joiner",
            "assigned_to",
        ).get(id=int(dispute_id))
    except (Dispute.DoesNotExist, ValueError):
        raise GraphQLError("Dispute not found.")


def _get_notification(notification_id):
    try:
        return Notification.objects.select_related("user").get(id=int(notification_id))
    except (Notification.DoesNotExist, ValueError):
        raise GraphQLError("Notification not found.")


def _deposit_status_from_payload(payload):
    return DepositStatusType(
        order_id=payload["order_id"],
        deposit_id=payload["deposit_id"],
        status=payload["status"],
        payment_provider=payload.get("payment_provider"),
        provider_payment_status=payload.get("provider_payment_status"),
        payment_reference=payload.get("payment_reference"),
        provider_transaction_id=payload.get("provider_transaction_id"),
        amount=Decimal(str(payload["amount"])),
        failure_reason=payload.get("failure_reason", ""),
        completed=payload["completed"],
        failed=payload["failed"],
        pending=payload["pending"],
        message=payload.get("message"),
        payment_url=payload.get("payment_url"),
    )


def _resolve_submitted_match_result(match, match_result):
    creator_sub = match_result.creator_submission
    joiner_sub = match_result.joiner_submission

    if (
        (creator_sub == "WON" and joiner_sub == "LOST")
        or (creator_sub == "LOST" and joiner_sub == "WON")
        or (creator_sub == "DRAW" and joiner_sub == "DRAW")
    ):
        if creator_sub == "DRAW":
            from matches.settlement import settle_match
            match = settle_match(match, draw=True)
            refund_amount = Decimal(match.amount) * Decimal("0.9")
            for player, opponent in ((match.creator, match.joiner), (match.joiner, match.creator)):
                Notification.objects.create(
                    user=player,
                    message=(
                        f"Your {match.get_game_display()} match against {opponent.username} "
                        f"ended in a draw. ZMW {refund_amount} has been returned to your wallet."
                    ),
                )
            return MatchPayload(message="Match recorded as a draw.", match=match, status=match.status)

        winner = match.creator if creator_sub == "WON" else match.joiner
        loser = match.joiner if winner == match.creator else match.creator
        from matches.settlement import settle_match
        match = settle_match(match, winner=winner)
        Notification.objects.create(
            user=winner,
            message=(
                f"Congratulations! You won the {match.get_game_display()} match against "
                f"{loser.username}. ZMW {match.winnings} has been added to your wallet."
            ),
        )
        Notification.objects.create(
            user=loser,
            message=f"You lost the {match.get_game_display()} match against {winner.username}.",
        )
        return MatchPayload(
            message="Match result recorded successfully.",
            match=match,
            status=match.status,
            winner_id=winner.id,
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
        return MatchPayload(message="Disagreement detected. Please submit results again.", match=match, round=2)

    match.status = "DISPUTED"
    match.save(update_fields=["status"])
    Dispute.objects.get_or_create(match=match, defaults={"status": "OPEN"})
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
    return MatchPayload(message="Match marked as disputed. Support will review.", match=match, status=match.status)
