"""
Centralized Lipila HTTP client — all provider API calls go through here.

Auth: x-api-key {LIPILA_SECRET_KEY} only.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urljoin

import requests
from django.conf import settings

logger = logging.getLogger('payments.lipila')


_SENSITIVE_HEADER_NAMES = {
    'authorization',
    'cookie',
    'set-cookie',
    'x-api-key',
}


def _build_url(base: str, path: str) -> str:
    if path.startswith('http://') or path.startswith('https://'):
        return path
    base_clean = base.rstrip('/')
    path_clean = path.lstrip('/')
    if base_clean.endswith('/api/v1') and path_clean.startswith('api/v1/'):
        path_clean = path_clean[len('api/v1/'):]
    return urljoin(base_clean + '/', path_clean)


def _redact_headers(headers) -> Dict[str, str]:
    return {
        key: '***REDACTED***' if key.lower() in _SENSITIVE_HEADER_NAMES else value
        for key, value in dict(headers or {}).items()
    }


class LipilaService:
    """Low-level Lipila REST client."""

    def __init__(
        self,
        secret_key: str,
        base_url: str,
        *,
        mobile_money_path: str = '/api/v1/collections/mobile-money',
        disbursement_base_url: Optional[str] = None,
        mobile_money_disbursement_path: str = '/api/v1/disbursements/mobile-money',
        status_path_template: str = '/collections/{reference_id}',
        legacy_collections: bool = False,
        timeout: int = 30,
    ) -> None:
        self.secret_key = (secret_key or '').strip()
        self.base_url = (base_url or '').rstrip('/')
        self.disbursement_base_url = (disbursement_base_url or self.base_url).rstrip('/')
        self.mobile_money_path = mobile_money_path
        self.mobile_money_disbursement_path = mobile_money_disbursement_path
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

    def _api_key_headers(self, *, callback_url: Optional[str] = None) -> Dict[str, str]:
        headers = {
            'accept': 'application/json',
            'Content-Type': 'application/json',
            'x-api-key': self.secret_key,
        }
        if callback_url:
            headers['callbackUrl'] = callback_url
        return headers

    @staticmethod
    def response_log_details(resp: Optional[requests.Response]) -> Dict[str, Any]:
        """Return response metadata useful for provider debugging."""
        if resp is None:
            return {}

        request = getattr(resp, 'request', None)
        try:
            body = resp.text
        except Exception as exc:
            body = f'<unable to decode response body: {exc}>'

        details = {
            'request_method': getattr(request, 'method', None),
            'request_url': getattr(request, 'url', None) or getattr(resp, 'url', None),
            'status_code': getattr(resp, 'status_code', None),
            'reason': getattr(resp, 'reason', ''),
            'response_headers': _redact_headers(getattr(resp, 'headers', {})),
            'response_body': body if body else '<empty>',
        }

        if request is not None:
            details['request_headers'] = _redact_headers(getattr(request, 'headers', {}))

        return details

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
        POST {LIPILA_BASE_URL}/api/v1/collections/mobile-money by default.
        Some older deployments configured /collections/mobile-money; if Lipila
        returns a missing-route response for that path, retry the api/v1 route.
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
            'identifier': reference_id,
            'externalReference': reference_id,
            'amount': amount,
            'currency': currency,
            'narration': narration,
            'referenceData': narration,
            'accountNumber': account_number,
            'phoneNumber': account_number,
        }
        if callback_url:
            payload['callbackUrl'] = callback_url
        if email:
            payload['email'] = email

        headers = self._api_key_headers(callback_url=callback_url)
        if idempotency_key:
            headers['Idempotency-Key'] = idempotency_key

        logger.info(
            'Lipila initiate mobile-money: ref=%s amount=%s currency=%s',
            reference_id,
            amount,
            currency,
        )
        resp = requests.post(url, json=payload, headers=headers, timeout=self.timeout)
        logger.info(
            'Lipila initiate response: http=%s body=%s',
            resp.status_code,
            resp.text[:500],
        )
        if self._should_retry_legacy_collection(resp, url):
            logger.warning(
                'Lipila collection endpoint missing at %s; retrying /api/v1/collections/mobile-money',
                url,
            )
            return self._legacy_collect_mobile_money(
                reference_id=reference_id,
                amount=amount,
                account_number=account_number,
                currency=currency,
                narration=narration,
                email=email,
                callback_url=callback_url,
                idempotency_key=idempotency_key,
            )
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

    @staticmethod
    def _should_retry_legacy_collection(resp: requests.Response, url: str) -> bool:
        body = (getattr(resp, 'text', '') or '').strip()
        return (
            not resp.ok
            and '/collections/mobile-money' in url
            and '/api/v1/collections/mobile-money' not in url
            and 'Cannot POST /collections/mobile-money' in body
        )

    def disburse_mobile_money(
        self,
        *,
        reference_id: str,
        amount: float,
        account_number: str,
        currency: str,
        narration: str = '',
        callback_url: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Initiate a Lipila mobile money disbursement."""
        url = _build_url(self.disbursement_base_url, self.mobile_money_disbursement_path)
        payload: Dict[str, Any] = {
            'referenceId': reference_id,
            'amount': amount,
            'accountNumber': account_number,
            'currency': currency,
        }
        if narration:
            payload['narration'] = narration

        headers = self._api_key_headers(callback_url=callback_url)
        if idempotency_key:
            headers['Idempotency-Key'] = idempotency_key

        logger.info(
            'Lipila mobile-money disbursement: ref=%s amount=%s currency=%s',
            reference_id,
            amount,
            currency,
        )
        resp = requests.post(url, json=payload, headers=headers, timeout=self.timeout)
        logger.info(
            'Lipila disbursement response: %s',
            self.response_log_details(resp),
        )
        if not resp.ok:
            logger.error(
                'Lipila disbursement failed: %s',
                self.response_log_details(resp),
            )
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    def _get_collection_status(self, reference_id: str) -> Optional[Dict[str, Any]]:
        """Try Lipila's documented collection status endpoint."""
        for path in ('/collections/check-status', '/api/v1/collections/check-status'):
            url = _build_url(self.base_url, path)
            resp = requests.post(
                url,
                json={'referenceId': reference_id},
                headers=self._headers(),
                timeout=self.timeout,
            )
            logger.info(
                'Lipila collection status check: ref=%s url=%s http=%s',
                reference_id,
                url,
                resp.status_code,
            )
            if resp.ok:
                return resp.json() if resp.content else {}
            if resp.status_code == 405:
                resp = requests.get(
                    url,
                    json={'referenceId': reference_id},
                    headers=self._headers(),
                    timeout=self.timeout,
                )
                logger.info(
                    'Lipila collection status check fallback: ref=%s url=%s http=%s',
                    reference_id,
                    url,
                    resp.status_code,
                )
                if resp.ok:
                    return resp.json() if resp.content else {}
            if resp.status_code == 400:
                logger.warning(
                    'Lipila collection status check rejected ref=%s body=%s',
                    reference_id,
                    resp.text[:300],
                )
                return None
            if resp.status_code != 404:
                resp.raise_for_status()
        return None

    def get_transaction_status(self, reference_id: str) -> Dict[str, Any]:
        collection_status = self._get_collection_status(reference_id)
        if collection_status is not None:
            return collection_status

        if self.legacy_collections:
            raise requests.HTTPError(
                f'Collection with referenceId {reference_id} was not found'
            )

        path = self.status_path_template.format(reference_id=reference_id)
        url = _build_url(self.base_url, path)
        resp = requests.get(url, headers=self._headers(), timeout=self.timeout)

        logger.info('Lipila status check: ref=%s http=%s', reference_id, resp.status_code)
        if resp.ok:
            return resp.json() if resp.content else {}

        resp.raise_for_status()
        return resp.json() if resp.content else {}

    def _legacy_collect_mobile_money(self, **kwargs) -> Dict[str, Any]:
        """Blaze docs style (x-api-key) for backward compatibility."""
        url = _build_url(self.base_url, '/api/v1/collections/mobile-money')
        reference_id = kwargs['reference_id']
        payload = {
            'referenceId': reference_id,
            'identifier': reference_id,
            'amount': kwargs['amount'],
            'narration': kwargs['narration'],
            'referenceData': kwargs['narration'],
            'accountNumber': kwargs['account_number'],
            'currency': kwargs['currency'],
        }
        if kwargs.get('callback_url'):
            payload['callbackUrl'] = kwargs['callback_url']
        if kwargs.get('email'):
            payload['email'] = kwargs['email']
        headers = {
            'accept': 'application/json',
            'Content-Type': 'application/json',
            'x-api-key': self.secret_key,
        }
        if kwargs.get('callback_url'):
            headers['callbackUrl'] = kwargs['callback_url']
        if kwargs.get('idempotency_key'):
            headers['Idempotency-Key'] = kwargs['idempotency_key']
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
        status = LipilaService.extract_status(response)
        message = str(
            response.get('message')
            or response.get('description')
            or ''
        ).strip()
        normalized = LipilaService.normalize_status(status)
        if normalized == 'Successful':
            return 'COMPLETED', message or status
        if normalized == 'Failed':
            return 'FAILED', message or status
        if normalized == 'Pending':
            return 'PENDING', message or status
        return 'UNKNOWN', message or status

    @staticmethod
    def extract_status(response: Dict[str, Any]) -> str:
        if not isinstance(response, dict):
            return ''

        for payload in LipilaService._candidate_payloads(response):
            status = str(
                payload.get('status')
                or payload.get('paymentStatus')
                or payload.get('payment_status')
                or payload.get('collectionStatus')
                or payload.get('transactionStatus')
                or ''
            ).strip()
            if status:
                return status
        return ''

    @staticmethod
    def extract_transaction_id(response: Dict[str, Any]) -> Optional[str]:
        if not isinstance(response, dict):
            return None
        for payload in LipilaService._candidate_payloads(response):
            value = str(
                payload.get('transactionId')
                or payload.get('transaction_id')
                or payload.get('identifier')
                or payload.get('externalId')
                or payload.get('id')
                or payload.get('referenceId')
                or ''
            ).strip()
            if value:
                return value
        return None

    @staticmethod
    def _candidate_payloads(response: Dict[str, Any]):
        yield response
        for key in ('data', 'transaction', 'collection', 'payment'):
            nested = response.get(key)
            if isinstance(nested, dict):
                yield nested


def get_lipila_service() -> LipilaService:
    secret = (
        getattr(settings, 'LIPILA_SECRET_KEY', '')
        or getattr(settings, 'LIPILA_API_KEY', '')
    ).strip()
    logger.info(
        "Lipila Config: base_url=%s disbursement_base_url=%s secret_present=%s secret_prefix=%s",
        getattr(settings, 'LIPILA_BASE_URL', ''),
        getattr(settings, 'LIPILA_DISBURSEMENT_BASE_URL', ''),
        bool(secret),
        secret[:8] if secret else 'EMPTY'
    )
    legacy = str(getattr(settings, 'LIPILA_API_STYLE', 'uat')).strip().lower() == 'legacy'
    return LipilaService(
        secret_key=secret,
        base_url=getattr(settings, 'LIPILA_BASE_URL', 'https://api.lipila.dev'),
        disbursement_base_url=getattr(
            settings,
            'LIPILA_DISBURSEMENT_BASE_URL',
            getattr(settings, 'LIPILA_BASE_URL', 'https://api.lipila.dev'),
        ),
        mobile_money_path=getattr(
            settings,
            'LIPILA_MOBILE_MONEY_PATH',
            '/api/v1/collections/mobile-money',
        ),
        mobile_money_disbursement_path=getattr(
            settings,
            'LIPILA_MOBILE_MONEY_DISBURSEMENT_PATH',
            '/api/v1/disbursements/mobile-money',
        ),
        status_path_template=getattr(
            settings,
            'LIPILA_STATUS_PATH_TEMPLATE',
            '/collections/{reference_id}',
        ),
        legacy_collections=legacy,
        timeout=int(getattr(settings, 'LIPILA_TIMEOUT_SECONDS', 60)),
    )
