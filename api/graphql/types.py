from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import strawberry


@strawberry.type
class ProfileType:
    first_name: str
    last_name: str


@strawberry.type
class MeType:
    id: strawberry.ID
    username: str
    email: str
    date_joined: datetime
    is_support_staff: bool
    is_active: bool

    @strawberry.field
    def profile(self) -> ProfileType | None:
        try:
            return self.profile
        except AttributeError:
            return None


@strawberry.type
class PublicUserType:
    id: strawberry.ID
    username: str
    date_joined: datetime

    @strawberry.field
    def profile(self) -> ProfileType | None:
        try:
            return self.profile
        except AttributeError:
            return None


@strawberry.type
class MatchType:
    id: strawberry.ID
    game: str
    device: str
    privacy: str
    joining_code: str
    amount: int
    winnings: int
    status: str
    created_at: datetime
    creator: PublicUserType
    joiner: PublicUserType | None
    winner: PublicUserType | None


@strawberry.type
class WalletType:
    id: strawberry.ID
    balance: Decimal


@strawberry.type
class TransactionType:
    id: strawberry.ID
    amount: Decimal
    transaction_type: str
    description: str
    created_at: datetime
    related_match: MatchType | None

    @strawberry.field
    def is_credit(self) -> bool:
        return self.is_credit


@strawberry.type
class DisputeType:
    id: strawberry.ID
    status: str
    created_at: datetime
    assigned_to: PublicUserType | None
    resolution_notes: str | None
    resolved_at: datetime | None
    match: MatchType

    @strawberry.field
    def match_id(self) -> strawberry.ID:
        return self.match_id

    @strawberry.field
    def match_game(self) -> str | None:
        return self.match.get_game_display() if self.match else None

    @strawberry.field
    def match_amount(self) -> int | None:
        return self.match.amount if self.match else None

    @strawberry.field
    def match_status(self) -> str | None:
        return self.match.status if self.match else None

    @strawberry.field
    def creator_username(self) -> str | None:
        return self.match.creator.username if self.match and self.match.creator else None

    @strawberry.field
    def joiner_username(self) -> str | None:
        return self.match.joiner.username if self.match and self.match.joiner else None


@strawberry.type
class MessageType:
    id: strawberry.ID
    sender: PublicUserType
    receiver: PublicUserType
    message: str
    created_at: datetime

    @strawberry.field
    def sender_username(self) -> str:
        return self.sender.username

    @strawberry.field
    def receiver_username(self) -> str:
        return self.receiver.username

    @strawberry.field
    def is_read(self, info: strawberry.Info) -> bool:
        from messenger.models import ReadMessage

        request_user = info.context.request.user
        if request_user.is_authenticated and request_user == self.receiver:
            return ReadMessage.objects.filter(message=self, receiver=request_user).exists()
        return False


@strawberry.type
class NotificationType:
    id: strawberry.ID
    user: PublicUserType
    message: str
    link: str | None
    created_at: datetime

    @strawberry.field
    def is_read(self, info: strawberry.Info) -> bool:
        from alert.models import ReadNotification

        request_user = info.context.request.user
        if request_user.is_authenticated:
            return ReadNotification.objects.filter(notification=self, user=request_user).exists()
        return False


@strawberry.type
class ConversationType:
    user: PublicUserType
    latest_message: MessageType | None
    unread_count: int

    @strawberry.field
    def user_id(self) -> strawberry.ID:
        return self.user.id

    @strawberry.field
    def username(self) -> str:
        return self.user.username


@strawberry.type
class AuthPayload:
    user: MeType
    access: str
    refresh: str


@strawberry.type
class TokenPayload:
    access: str
    refresh: str | None = None


@strawberry.type
class TokenVerificationPayload:
    valid: bool
    token_type: str | None = None
    user_id: strawberry.ID | None = None
    expires_at: int | None = None


@strawberry.type
class MessagePayload:
    message: str
    status: str | None = None


@strawberry.type
class MatchPayload:
    message: str
    match: MatchType | None = None
    status: str | None = None
    winner_id: strawberry.ID | None = None
    round: int | None = None


@strawberry.type
class DepositStatusType:
    order_id: strawberry.ID
    deposit_id: strawberry.ID
    status: str
    payment_provider: str | None
    provider_payment_status: str | None
    payment_reference: str | None
    provider_transaction_id: str | None
    amount: Decimal
    failure_reason: str
    completed: bool
    failed: bool
    pending: bool
    message: str | None = None
    payment_url: str | None = None


@strawberry.type
class WithdrawalPayload:
    withdrawal_id: strawberry.ID
    status: str
    amount: Decimal
    payment_method: str
    transaction_id: str | None
    gateway_transaction_id: str | None
    message: str
