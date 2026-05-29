"""
Centralized Lipila HTTP client — all provider API calls go through here.

Auth: Bearer {LIPILA_SECRET_KEY} only (no public key).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urljoin

import requests
from django.conf import settings

logger = logging.getLogger('payments.lipila')


def _build_url(base: str, path: str) -> str:
    if path.startswith('http://') or path.startswith('https://'):
        return path
    return urljoin(base.rstrip('/') + '/', path.lstrip('/'))


class LipilaService:
    """Low-level Lipila REST client."""

    def __init__(
        self,
        secret_key: str,
        base_url: str,
        *,
        mobile_money_path: str = '/collections/mobile-money',
        status_path_template: str = '/collections/{reference_id}',
        legacy_collections: bool = False,
        timeout: int = 30,
    ) -> None:
        self.secret_key = (secret_key or '').strip()
        self.base_url = (base_url or '').rstrip('/')
        self.mobile_money_path = mobile_money_path
        self.status_path_template = status_path_template
        self.legacy_collections = legacy_collections
        self.timeout = timeout

    def _headers(self, *, callback_url: Optional[str] = None) -> Dict[str, str]:
        headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'x-api-key': self.secret_key,
            'Authorization': f'Bearer {self.secret_key}',
        }
        if callback_url:
            headers['callbackUrl'] = callback_url
        return headers

    def initiate_mobile_money(
        self,
        *,
        reference_id: str,
        amount: float,
        account_number: str,
        currency: str,
        narration: str,
        email: Optional[str] = None,
        callback_url: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        POST {LIPILA_BASE_URL}/collections/mobile-money (UAT/production style)
        or legacy /api/v1/collections/mobile-money when LIPILA_API_STYLE=legacy.
        """
        if self.legacy_collections:
            return self._legacy_collect_mobile_money(
                reference_id=reference_id,
                amount=amount,
                account_number=account_number,
                currency=currency,
                narration=narration,
                email=email,
                callback_url=callback_url,
            )

        url = _build_url(self.base_url, self.mobile_money_path)
        payload: Dict[str, Any] = {
            'referenceId': reference_id,
            'externalReference': reference_id,
            'amount': amount,
            'currency': currency,
            'narration': narration,
            'accountNumber': account_number,
            'phoneNumber': account_number,
        }
        if email:
            payload['email'] = email

        headers = self._headers(callback_url=callback_url)
        if idempotency_key:
            headers['Idempotency-Key'] = idempotency_key

        logger.info(
            'Lipila initiate mobile-money: ref=%s amount=%s currency=%s',
            reference_id,
            amount,
            currency,
        )
        resp = requests.post(url, json=payload, headers=headers, timeout=self.timeout)
        logger.info('Lipila initiate response: http=%s', resp.status_code)
        if not resp.ok:
            logger.error(
                'Lipila initiate failed: http=%s body=%s',
                resp.status_code,
                resp.text[:500],
            )
        resp.raise_for_status()
        data = resp.json() if resp.content else {}
        logger.debug('Lipila initiate body keys: %s', list(data.keys()) if isinstance(data, dict) else type(data))
        return data

    def get_transaction_status(self, reference_id: str) -> Dict[str, Any]:
        if self.legacy_collections:
            url = _build_url(self.base_url, '/api/v1/collections/check-status')
            resp = requests.get(
                url,
                params={'referenceId': reference_id},
                headers=self._headers(),
                timeout=self.timeout,
            )
        else:
            path = self.status_path_template.format(reference_id=reference_id)
            url = _build_url(self.base_url, path)
            resp = requests.get(url, headers=self._headers(), timeout=self.timeout)

        logger.info('Lipila status check: ref=%s http=%s', reference_id, resp.status_code)
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    def _legacy_collect_mobile_money(self, **kwargs) -> Dict[str, Any]:
        """Blaze docs style (x-api-key) for backward compatibility."""
        url = _build_url(self.base_url, '/api/v1/collections/mobile-money')
        reference_id = kwargs['reference_id']
        payload = {
            'referenceId': reference_id,
            'amount': kwargs['amount'],
            'narration': kwargs['narration'],
            'accountNumber': kwargs['account_number'],
            'currency': kwargs['currency'],
        }
        if kwargs.get('email'):
            payload['email'] = kwargs['email']
        headers = {
            'accept': 'application/json',
            'Content-Type': 'application/json',
            'x-api-key': self.secret_key,
        }
        if kwargs.get('callback_url'):
            headers['callbackUrl'] = kwargs['callback_url']
        resp = requests.post(url, json=payload, headers=headers, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    @staticmethod
    def normalize_status(raw_status: str) -> str:
        s = (raw_status or '').strip().upper()
        if s in ('SUCCESSFUL', 'SUCCESS', 'COMPLETED', 'PAID'):
            return 'Successful'
        if s in ('FAILED', 'CANCELLED', 'CANCELED', 'REJECTED'):
            return 'Failed'
        return 'Pending'

    @staticmethod
    def interpret_status(response: Dict[str, Any]) -> Tuple[str, str]:
        """
        Map provider response to internal deposit status + message.
        Returns (COMPLETED|FAILED|PENDING|UNKNOWN, message).
        """
        if not isinstance(response, dict):
            return 'UNKNOWN', ''
        status = str(
            response.get('status')
            or response.get('paymentStatus')
            or ''
        ).strip()
        message = str(response.get('message') or '').strip()
        normalized = LipilaService.normalize_status(status)
        if normalized == 'Successful':
            return 'COMPLETED', message or status
        if normalized == 'Failed':
            return 'FAILED', message or status
        if normalized == 'Pending':
            return 'PENDING', message or status
        return 'UNKNOWN', message or status

    @staticmethod
    def extract_transaction_id(response: Dict[str, Any]) -> Optional[str]:
        if not isinstance(response, dict):
            return None
        return str(
            response.get('transactionId')
            or response.get('transaction_id')
            or response.get('identifier')
            or response.get('id')
            or response.get('referenceId')
            or ''
        ).strip() or None


def get_lipila_service() -> LipilaService:
    secret = (
        getattr(settings, 'LIPILA_SECRET_KEY', '')
        or getattr(settings, 'LIPILA_API_KEY', '')
    ).strip()
    logger.info(
        "Lipila Config: base_url=%s secret_present=%s secret_prefix=%s",
        getattr(settings, 'LIPILA_BASE_URL', ''),
        bool(secret),
        secret[:8] if secret else 'EMPTY'
    )
    legacy = str(getattr(settings, 'LIPILA_API_STYLE', 'uat')).strip().lower() == 'legacy'
    return LipilaService(
        secret_key=secret,
        base_url=getattr(settings, 'LIPILA_BASE_URL', 'https://lipila-uat.hobbiton.app'),
        mobile_money_path=getattr(
            settings,
            'LIPILA_MOBILE_MONEY_PATH',
            '/collections/mobile-money',
        ),
        status_path_template=getattr(
            settings,
            'LIPILA_STATUS_PATH_TEMPLATE',
            '/collections/{reference_id}',
        ),
        legacy_collections=legacy,
        timeout=int(getattr(settings, 'LIPILA_TIMEOUT_SECONDS', 30)),
    )
