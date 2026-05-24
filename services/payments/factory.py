"""
Payment provider factory — select gateway from PAYMENT_PROVIDER setting.
"""
from __future__ import annotations

from django.conf import settings

from services.payments.base import PaymentGateway
from services.payments.lipila_gateway import LipilaGateway

_GATEWAY_CACHE: PaymentGateway | None = None


def get_payment_gateway(force_refresh: bool = False) -> PaymentGateway:
    global _GATEWAY_CACHE
    if _GATEWAY_CACHE is not None and not force_refresh:
        return _GATEWAY_CACHE

    provider = str(getattr(settings, 'PAYMENT_PROVIDER', 'lipila')).strip().lower()
    if provider == 'lipila':
        _GATEWAY_CACHE = LipilaGateway()
        return _GATEWAY_CACHE

    raise ValueError(f'Unsupported PAYMENT_PROVIDER: {provider}')
