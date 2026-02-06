"""
Pesapal API client (v3-style).

This module is intentionally defensive about endpoints/field names because Pesapal
deployments differ slightly between environments. Endpoints are configurable via
Django settings.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urljoin

import requests
from django.conf import settings

logger = logging.getLogger(__name__)
from wallet.payment_debug import payment_debug_enabled


def _bool_status(val: Any) -> bool:
    return val in (True, 'true', 'True', 'success', 'SUCCESS', 'ok', 'OK')


def _pick(d: Dict[str, Any], *keys: str) -> Any:
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def _build_url(base: str, endpoint: str) -> str:
    if endpoint.startswith('http://') or endpoint.startswith('https://'):
        return endpoint
    base = (base or '').rstrip('/') + '/'
    endpoint = endpoint.lstrip('/')
    return urljoin(base, endpoint)


@dataclass
class PesapalCredentials:
    consumer_key: str
    consumer_secret: str


class PesapalClient:
    def __init__(
        self,
        credentials: PesapalCredentials,
        base_url: str,
        auth_endpoint: str,
        submit_order_endpoint: str,
        txn_status_endpoint: str,
        register_ipn_endpoint: str,
    ) -> None:
        self.credentials = credentials
        self.base_url = base_url
        self.auth_endpoint = auth_endpoint
        self.submit_order_endpoint = submit_order_endpoint
        self.txn_status_endpoint = txn_status_endpoint
        self.register_ipn_endpoint = register_ipn_endpoint

        self._token: Optional[str] = None
        self._token_exp: float = 0.0

    def _request_token(self) -> str:
        # Reuse cached token when possible
        now = time.time()
        if self._token and now < self._token_exp:
            return self._token

        url = _build_url(self.base_url, self.auth_endpoint)
        payload = {
            'consumer_key': self.credentials.consumer_key,
            'consumer_secret': self.credentials.consumer_secret,
        }

        if payment_debug_enabled():
            logger.info("[PAYMENT_DEBUG] pesapal_token_request: url=%s", url)
        resp = requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json() if resp.content else {}
        if payment_debug_enabled():
            logger.info("[PAYMENT_DEBUG] pesapal_token_response: keys=%s", sorted(list(data.keys())) if isinstance(data, dict) else type(data).__name__)

        # Pesapal sometimes returns structured errors in a 200 response; surface them clearly.
        if isinstance(data, dict) and data.get("error"):
            err = data.get("error") or {}
            err_type = _pick(err, "error_type", "type") or "unknown_error"
            err_code = _pick(err, "code", "error_code") or "unknown_code"
            err_msg = _pick(err, "message", "error_message") or ""
            raise ValueError(
                f"Pesapal token request failed: type={err_type} code={err_code} message={err_msg}".strip()
            )

        token = _pick(data, 'token', 'access_token', 'Token', 'AccessToken')
        expires_in = _pick(data, 'expires_in', 'expiresIn', 'expiry', 'expires') or 300

        if not token:
            raise ValueError(f'Pesapal token missing in response: {data}')

        try:
            expires_in_int = int(expires_in)
        except Exception:
            expires_in_int = 300

        # refresh a bit early
        self._token = str(token)
        self._token_exp = now + max(30, expires_in_int - 30)
        return self._token

    def _auth_headers(self) -> Dict[str, str]:
        token = self._request_token()
        return {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }

    def register_ipn(self, ipn_url: str, notification_type: str = 'GET') -> Dict[str, Any]:
        url = _build_url(self.base_url, self.register_ipn_endpoint)
        payload = {
            'url': ipn_url,
            'ipn_notification_type': notification_type,
        }
        if payment_debug_enabled():
            logger.info("[PAYMENT_DEBUG] pesapal_register_ipn: url=%s ipn_url=%s type=%s", url, ipn_url, notification_type)
        resp = requests.post(url, json=payload, headers=self._auth_headers(), timeout=30)
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    def submit_order(
        self,
        merchant_reference: str,
        amount: str,
        currency: str,
        description: str,
        callback_url: str,
        notification_id: str,
        email: str,
        phone_number: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        url = _build_url(self.base_url, self.submit_order_endpoint)
        payload: Dict[str, Any] = {
            'id': merchant_reference,
            'currency': currency,
            'amount': amount,
            'description': description,
            'callback_url': callback_url,
            'notification_id': notification_id,
            'billing_address': {
                'email_address': email,
            },
        }
        if phone_number:
            payload['billing_address']['phone_number'] = phone_number
        if first_name:
            payload['billing_address']['first_name'] = first_name
        if last_name:
            payload['billing_address']['last_name'] = last_name

        resp = requests.post(url, json=payload, headers=self._auth_headers(), timeout=30)
        resp.raise_for_status()
        if payment_debug_enabled():
            try:
                j = resp.json() if resp.content else {}
            except Exception:
                j = {"_non_json": True}
            logger.info("[PAYMENT_DEBUG] pesapal_submit_order_response: http=%s keys=%s", resp.status_code, sorted(list(j.keys())) if isinstance(j, dict) else type(j).__name__)
        return resp.json() if resp.content else {}

    def get_transaction_status(self, order_tracking_id: str) -> Dict[str, Any]:
        url = _build_url(self.base_url, self.txn_status_endpoint)
        # Most Pesapal docs show orderTrackingId as query param
        resp = requests.get(
            url,
            params={'orderTrackingId': order_tracking_id},
            headers=self._auth_headers(),
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    @staticmethod
    def interpret_status(status_response: Dict[str, Any]) -> Tuple[str, str]:
        """
        Returns (normalized_status, raw_description)

        normalized_status ∈ {"COMPLETED","FAILED","PENDING","UNKNOWN"}
        """
        data = status_response.get('data', status_response) if isinstance(status_response, dict) else {}
        desc = _pick(
            data,
            'payment_status_description',
            'paymentStatusDescription',
            'status_description',
            'statusDescription',
            'status',
        )
        desc_str = (str(desc) if desc is not None else '').strip()
        desc_upper = desc_str.upper()

        if desc_upper in ('COMPLETED', 'SUCCESS', 'SUCCEEDED', 'PAID'):
            return 'COMPLETED', desc_str
        if desc_upper in ('FAILED', 'CANCELLED', 'CANCELED', 'INVALID'):
            return 'FAILED', desc_str
        if desc_upper in ('PENDING', 'PROCESSING', 'IN_PROGRESS'):
            return 'PENDING', desc_str

        # Some environments return a boolean status plus message
        if _bool_status(status_response.get('status')):
            return 'PENDING', desc_str or 'success'

        return 'UNKNOWN', desc_str


def get_pesapal_client() -> PesapalClient:
    creds = PesapalCredentials(
        consumer_key=getattr(settings, 'PESAPAL_CONSUMER_KEY', '') or '',
        consumer_secret=getattr(settings, 'PESAPAL_CONSUMER_SECRET', '') or '',
    )
    return PesapalClient(
        credentials=creds,
        base_url=getattr(settings, 'PESAPAL_BASE_URL', ''),
        auth_endpoint=getattr(settings, 'PESAPAL_AUTH_ENDPOINT', '/api/Auth/RequestToken'),
        submit_order_endpoint=getattr(settings, 'PESAPAL_SUBMIT_ORDER_ENDPOINT', '/api/Transactions/SubmitOrderRequest'),
        txn_status_endpoint=getattr(settings, 'PESAPAL_TXN_STATUS_ENDPOINT', '/api/Transactions/GetTransactionStatus'),
        register_ipn_endpoint=getattr(settings, 'PESAPAL_REGISTER_IPN_ENDPOINT', '/api/URLSetup/RegisterIPN'),
    )

