from __future__ import annotations

import strawberry
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.contrib.auth import get_user_model
from django.db.models import Q
from graphql import GraphQLError
from strawberry.extensions import MaxAliasesLimiter, MaxTokensLimiter, QueryDepthLimiter

from alert.models import Notification, ReadNotification
from matches.models import Match
from messenger.models import Message, ReadMessage
from panel.models import Dispute
from wallet.models import Transaction, Wallet

from .mutations import Mutation
from .types import (
    ConversationType,
    DepositStatusType,
    DisputeType,
    MatchType,
    MeType,
    MessageType,
    NotificationType,
    ProfileType,
    PublicUserType,
    TransactionType,
    WalletType,
)
from .utils import require_authenticated_user, validation_error

User = get_user_model()


@strawberry.type
class Query:
    @strawberry.field
    def me(self, info: strawberry.Info) -> MeType | None:
        user = info.context.request.user
        if isinstance(user, AnonymousUser) or not user.is_authenticated:
            return None
        return user

    @strawberry.field
    def wallet(self, info: strawberry.Info) -> WalletType:
        user = require_authenticated_user(info)
        wallet, _created = Wallet.objects.get_or_create(user=user)
        return wallet

    @strawberry.field
    def profile(self, info: strawberry.Info) -> ProfileType:
        user = require_authenticated_user(info)
        profile, _created = user.profile.__class__.objects.get_or_create(user=user)
        return profile

    @strawberry.field
    def users(self, info: strawberry.Info, username: str | None = None) -> list[PublicUserType]:
        user = require_authenticated_user(info)
        if not user.is_staff:
            validation_error("Only staff users can list users.")
        queryset = User.objects.select_related("profile").order_by("-date_joined")
        if username:
            queryset = queryset.filter(username__icontains=username)
        return queryset

    @strawberry.field
    def user(self, info: strawberry.Info, id: strawberry.ID) -> PublicUserType:
        try:
            return User.objects.select_related("profile").get(id=int(id))
        except (User.DoesNotExist, ValueError):
            raise GraphQLError("User not found.")

    @strawberry.field
    def transactions(self, info: strawberry.Info) -> list[TransactionType]:
        user = require_authenticated_user(info)
        return (
            Transaction.objects
            .filter(wallet__user=user)
            .select_related(
                "related_match",
                "related_match__creator",
                "related_match__joiner",
                "related_match__winner",
            )
            .order_by("-created_at")
        )

    @strawberry.field
    def matches(
        self,
        info: strawberry.Info,
        status: str | None = None,
        game: str | None = None,
        device: str | None = None,
        privacy: str | None = None,
        available: bool = False,
    ) -> list[MatchType]:
        require_authenticated_user(info)
        queryset = (
            Match.objects
            .select_related("creator", "joiner", "winner")
            .order_by("-created_at")
        )

        if status:
            queryset = queryset.filter(status=status)
        if game:
            queryset = queryset.filter(game=game)
        if device:
            queryset = queryset.filter(device=device)
        if privacy:
            queryset = queryset.filter(privacy=privacy)
        if available:
            queryset = queryset.filter(status="OPEN", privacy="PUBLIC")

        return queryset

    @strawberry.field
    def match(self, info: strawberry.Info, id: strawberry.ID) -> MatchType:
        user = require_authenticated_user(info)
        try:
            match = Match.objects.select_related("creator", "joiner", "winner").get(id=int(id))
        except (Match.DoesNotExist, ValueError):
            raise GraphQLError("Match not found.")
        if match.privacy == "PRIVATE" and user not in [match.creator, match.joiner]:
            validation_error("You do not have access to this match.")
        return match

    @strawberry.field
    def my_matches(self, info: strawberry.Info) -> list[MatchType]:
        user = require_authenticated_user(info)
        return (
            Match.objects
            .filter(Q(creator=user) | Q(joiner=user))
            .select_related("creator", "joiner", "winner")
            .order_by("-created_at")
        )

    @strawberry.field
    def payment_status(self, info: strawberry.Info, order_id: strawberry.ID) -> DepositStatusType:
        user = require_authenticated_user(info)
        from services.payments.factory import get_payment_gateway
        from wallet.models import Deposit
        from wallet.payment_processing import apply_deposit_webhook_status
        from wallet.utils import get_deposit_payment_status_payload

        try:
            deposit = Deposit.objects.get(id=int(order_id), user=user)
        except (Deposit.DoesNotExist, ValueError):
            raise GraphQLError("Deposit not found.")

        if deposit.status in ("PENDING", "PROCESSING") and deposit.payment_provider == "lipila":
            gateway = get_payment_gateway(deposit.payment_provider)
            verify = gateway.verify_payment(deposit)
            if verify.payment_status == "Successful":
                apply_deposit_webhook_status(
                    deposit,
                    payment_status="Successful",
                    provider_transaction_id=verify.provider_transaction_id,
                    raw_payload=verify.raw_response,
                )
                deposit.refresh_from_db()
            elif verify.payment_status == "Failed":
                apply_deposit_webhook_status(
                    deposit,
                    payment_status="Failed",
                    provider_transaction_id=verify.provider_transaction_id,
                    raw_payload=verify.raw_response,
                )
                deposit.refresh_from_db()

        from .mutations import _deposit_status_from_payload

        return _deposit_status_from_payload(get_deposit_payment_status_payload(deposit))

    @strawberry.field
    def disputes(self, info: strawberry.Info, status: str | None = None) -> list[DisputeType]:
        user = require_authenticated_user(info)
        if user.is_support_staff or user.is_staff:
            queryset = Dispute.objects.all()
        else:
            queryset = Dispute.objects.filter(Q(match__creator=user) | Q(match__joiner=user))
        if status:
            queryset = queryset.filter(status=status)
        return queryset.select_related("match", "match__creator", "match__joiner", "assigned_to").order_by("-created_at")

    @strawberry.field
    def dispute(self, info: strawberry.Info, id: strawberry.ID) -> DisputeType:
        user = require_authenticated_user(info)
        queryset = Dispute.objects.select_related("match", "match__creator", "match__joiner", "assigned_to")
        if not (user.is_support_staff or user.is_staff):
            queryset = queryset.filter(Q(match__creator=user) | Q(match__joiner=user))
        try:
            return queryset.get(id=int(id))
        except (Dispute.DoesNotExist, ValueError):
            raise GraphQLError("Dispute not found.")

    @strawberry.field
    def messages(self, info: strawberry.Info) -> list[MessageType]:
        user = require_authenticated_user(info)
        return (
            Message.objects
            .filter(Q(sender=user) | Q(receiver=user))
            .select_related("sender", "receiver")
            .order_by("-created_at")
        )

    @strawberry.field
    def message(self, info: strawberry.Info, id: strawberry.ID) -> MessageType:
        user = require_authenticated_user(info)
        try:
            return (
                Message.objects
                .select_related("sender", "receiver")
                .filter(Q(sender=user) | Q(receiver=user))
                .get(id=int(id))
            )
        except (Message.DoesNotExist, ValueError):
            raise GraphQLError("Message not found.")

    @strawberry.field
    def conversations(self, info: strawberry.Info) -> list[ConversationType]:
        user = require_authenticated_user(info)
        other_users = (
            User.objects
            .filter(Q(sent_messages__receiver=user) | Q(received_messages__sender=user))
            .distinct()
            .exclude(id=user.id)
        )
        conversations = []
        for other_user in other_users:
            latest_message = (
                Message.objects
                .filter((Q(sender=user) & Q(receiver=other_user)) | (Q(sender=other_user) & Q(receiver=user)))
                .select_related("sender", "receiver")
                .order_by("-created_at")
                .first()
            )
            unread_count = (
                Message.objects
                .filter(sender=other_user, receiver=user)
                .exclude(id__in=ReadMessage.objects.filter(receiver=user).values_list("message_id", flat=True))
                .count()
            )
            conversations.append(ConversationType(user=other_user, latest_message=latest_message, unread_count=unread_count))
        return conversations

    @strawberry.field
    def conversation(self, info: strawberry.Info, user_id: strawberry.ID) -> list[MessageType]:
        user = require_authenticated_user(info)
        try:
            other_user = User.objects.get(id=int(user_id))
        except (User.DoesNotExist, ValueError):
            raise GraphQLError("User not found.")

        messages = (
            Message.objects
            .filter((Q(sender=user) & Q(receiver=other_user)) | (Q(sender=other_user) & Q(receiver=user)))
            .select_related("sender", "receiver")
            .order_by("created_at")
        )
        unread_messages = Message.objects.filter(sender=other_user, receiver=user).exclude(
            id__in=ReadMessage.objects.filter(receiver=user).values_list("message_id", flat=True)
        )
        for msg in unread_messages:
            ReadMessage.objects.get_or_create(message=msg, receiver=user)
        return messages

    @strawberry.field
    def notifications(self, info: strawberry.Info) -> list[NotificationType]:
        user = require_authenticated_user(info)
        return Notification.objects.filter(user=user).select_related("user").order_by("-created_at")

    @strawberry.field
    def notification(self, info: strawberry.Info, id: strawberry.ID) -> NotificationType:
        user = require_authenticated_user(info)
        try:
            return Notification.objects.select_related("user").get(id=int(id), user=user)
        except (Notification.DoesNotExist, ValueError):
            raise GraphQLError("Notification not found.")

    @strawberry.field
    def unread_notification_count(self, info: strawberry.Info) -> int:
        user = require_authenticated_user(info)
        return (
            Notification.objects
            .filter(user=user)
            .exclude(id__in=ReadNotification.objects.filter(user=user).values_list("notification_id", flat=True))
            .count()
        )


schema = strawberry.Schema(
    query=Query,
    mutation=Mutation,
    extensions=[
        QueryDepthLimiter(max_depth=settings.GRAPHQL_MAX_QUERY_DEPTH),
        MaxTokensLimiter(max_token_count=settings.GRAPHQL_MAX_QUERY_TOKENS),
        MaxAliasesLimiter(max_alias_count=settings.GRAPHQL_MAX_ALIASES),
    ],
)
