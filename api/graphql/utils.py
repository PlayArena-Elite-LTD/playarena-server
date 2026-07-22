import json
import re
import time

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from graphql import GraphQLError


def require_authenticated_user(info):
    user = info.context.request.user
    if isinstance(user, AnonymousUser) or not user.is_authenticated:
        raise GraphQLError("Authentication required.")
    return user


def serializer_error(serializer):
    raise GraphQLError(_stringify(serializer.errors))


def validation_error(message):
    raise GraphQLError(_stringify(message))


def enforce_graphql_rate_limit(info, scope, identifier=None):
    rates = getattr(settings, "GRAPHQL_AUTH_THROTTLE_RATES", {})
    rate = rates.get(scope)
    if not rate:
        return

    limit, window = _parse_rate(rate)
    request = info.context.request
    ip_address = _client_ip(request)
    identity = _clean_identifier(identifier or "")
    cache_key = f"graphql_auth_rl:{scope}:{ip_address}:{identity}"
    now = int(time.time())

    bucket = cache.get(cache_key)
    if not bucket or bucket.get("expires_at", 0) <= now:
        cache.set(cache_key, {"count": 1, "expires_at": now + window}, timeout=window)
        return

    if bucket["count"] >= limit:
        raise GraphQLError("Too many requests. Please try again later.")

    bucket["count"] += 1
    cache.set(cache_key, bucket, timeout=max(bucket["expires_at"] - now, 1))


def _parse_rate(rate):
    match = re.fullmatch(r"\s*(\d+)\s*/\s*([smhd])\s*", str(rate))
    if not match:
        raise ValueError(f"Invalid GraphQL throttle rate: {rate}")
    limit = int(match.group(1))
    period = match.group(2)
    seconds = {
        "s": 1,
        "m": 60,
        "h": 60 * 60,
        "d": 24 * 60 * 60,
    }[period]
    return limit, seconds


def _client_ip(request):
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


def _clean_identifier(value):
    return re.sub(r"[^a-zA-Z0-9@._+-]", "_", str(value).lower())[:128]


def _stringify(value):
    if isinstance(value, str):
        return value
    return json.dumps(value, default=str)
