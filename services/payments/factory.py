"""Payment provider factory and runtime provider selection."""
from __future__ import annotations

from django.conf import settings

from services.payments.base import PaymentGateway
from services.payments.lipila_gateway import LipilaGateway
from services.payments.zynle_gateway import ZynleGateway

_GATEWAY_CACHE: dict[str, PaymentGateway] = {}


def get_active_payment_provider() -> str:
    """Return the admin-selected provider, falling back during migrations/startup."""
    fallback = str(getattr(settings, 'PAYMENT_PROVIDER', 'lipila')).strip().lower()
    try:
        from wallet.models import PaymentGatewaySetting

        configured = PaymentGatewaySetting.objects.filter(pk=1).values_list(
            'active_provider', flat=True
        ).first()
        return str(configured or fallback).strip().lower()
    except Exception:
        # The table may not exist yet while migrations are running.
        return fallback


def get_payment_gateway(
    provider: str | None = None,
    force_refresh: bool = False,
) -> PaymentGateway:
    provider = str(provider or get_active_payment_provider()).strip().lower()
    if provider in _GATEWAY_CACHE and not force_refresh:
        return _GATEWAY_CACHE[provider]

    if provider == 'lipila':
        _GATEWAY_CACHE[provider] = LipilaGateway()
    elif provider == 'zynle':
        _GATEWAY_CACHE[provider] = ZynleGateway()
    else:
        raise ValueError(f'Unsupported payment provider: {provider}')

    return _GATEWAY_CACHE[provider]
