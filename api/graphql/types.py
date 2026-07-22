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
