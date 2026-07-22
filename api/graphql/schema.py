from __future__ import annotations

import strawberry
from django.contrib.auth.models import AnonymousUser
from django.db.models import Q
from graphql import GraphQLError

from matches.models import Match
from wallet.models import Transaction, Wallet

from .types import MatchType, MeType, TransactionType, WalletType


def require_authenticated_user(info: strawberry.Info):
    user = info.context.request.user
    if isinstance(user, AnonymousUser) or not user.is_authenticated:
        raise GraphQLError("Authentication required.")
    return user


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
    def my_matches(self, info: strawberry.Info) -> list[MatchType]:
        user = require_authenticated_user(info)
        return (
            Match.objects
            .filter(Q(creator=user) | Q(joiner=user))
            .select_related("creator", "joiner", "winner")
            .order_by("-created_at")
        )


schema = strawberry.Schema(query=Query)
