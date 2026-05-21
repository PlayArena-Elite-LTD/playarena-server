"""
Lipila API client (collections, disbursements, status checks).

Docs: https://blaze-docs.lipila.dev/
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urljoin

import requests
from django.conf import settings

from wallet.payment_debug import payment_debug_enabled

logger = logging.getLogger(__name__)


def _build_url(base: str, path: str) -> str:
    if path.startswith('http://') or path.startswith('https://'):
        return path
    base = (base or '').rstrip('/') + '/'
    return urljoin(base, path.lstrip('/'))


class LipilaClient:
    def __init__(self, api_key: str, base_url: str) -> None:
        self.api_key = (api_key or '').strip()
        self.base_url = (base_url or 'https://api.lipila.dev').rstrip('/')

    def _headers(self, callback_url: Optional[str] = None) -> Dict[str, str]:
        headers = {
            'accept': 'application/json',
            'Content-Type': 'application/json',
            'x-api-key': self.api_key,
        }
        if callback_url:
            headers['callbackUrl'] = callback_url
        return headers

    def collect_mobile_money(
        self,
        *,
        reference_id: str,
        amount: float,
        account_number: str,
        currency: str,
        narration: str,
        email: Optional[str] = None,
        callback_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        url = _build_url(self.base_url, '/api/v1/collections/mobile-money')
        payload: Dict[str, Any] = {
            'referenceId': reference_id,
            'amount': amount,
            'narration': narration,
            'accountNumber': account_number,
            'currency': currency,
        }
        if email:
            payload['email'] = email
        if payment_debug_enabled():
            logger.info('[PAYMENT_DEBUG] lipila_momo_collection: url=%s ref=%s', url, reference_id)
        resp = requests.post(url, json=payload, headers=self._headers(callback_url), timeout=30)
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    def collect_card(
        self,
        *,
        reference_id: str,
        amount: float,
        account_number: str,
        currency: str,
        narration: str,
        email: str,
        first_name: str,
        last_name: str,
        phone_number: str,
        redirect_url: str,
        back_url: str,
        city: str = 'Lusaka',
        country: str = 'ZM',
        address: str = 'N/A',
        zip_code: str = '10101',
        callback_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        url = _build_url(self.base_url, '/api/v1/collections/card')
        payload = {
            'customerInfo': {
                'firstName': first_name,
                'lastName': last_name,
                'phoneNumber': phone_number,
                'city': city,
                'country': country,
                'address': address,
                'zip': zip_code,
                'email': email,
            },
            'collectionRequest': {
                'referenceId': reference_id,
                'amount': amount,
                'narration': narration,
                'accountNumber': account_number,
                'currency': currency,
                'backUrl': back_url,
                'redirectUrl': redirect_url,
            },
        }
        if payment_debug_enabled():
            logger.info('[PAYMENT_DEBUG] lipila_card_collection: url=%s ref=%s', url, reference_id)
        resp = requests.post(url, json=payload, headers=self._headers(callback_url), timeout=30)
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    def check_collection_status(self, reference_id: str) -> Dict[str, Any]:
        url = _build_url(self.base_url, '/api/v1/collections/check-status')
        if payment_debug_enabled():
            logger.info('[PAYMENT_DEBUG] lipila_check_status: ref=%s', reference_id)
        resp = requests.get(
            url,
            params={'referenceId': reference_id},
            headers=self._headers(),
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    def disburse_mobile_money(
        self,
        *,
        reference_id: str,
        amount: float,
        account_number: str,
        currency: str,
        narration: str,
        callback_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        url = _build_url(self.base_url, '/api/v1/disbursements/mobile-money')
        payload = {
            'referenceId': reference_id,
            'amount': amount,
            'narration': narration,
            'accountNumber': account_number,
            'currency': currency,
        }
        if payment_debug_enabled():
            logger.info('[PAYMENT_DEBUG] lipila_momo_disbursement: url=%s ref=%s', url, reference_id)
        resp = requests.post(url, json=payload, headers=self._headers(callback_url), timeout=30)
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    @staticmethod
    def interpret_status(status_response: Dict[str, Any]) -> Tuple[str, str]:
        """
        Returns (normalized_status, raw_message)

        normalized_status ∈ {"COMPLETED", "FAILED", "PENDING", "UNKNOWN"}
        """
        if not isinstance(status_response, dict):
            return 'UNKNOWN', ''

        status = str(status_response.get('status', '')).strip()
        message = str(status_response.get('message', '')).strip()
        status_upper = status.upper()

        if status_upper in ('SUCCESSFUL', 'SUCCESS', 'COMPLETED', 'PAID'):
            return 'COMPLETED', message or status
        if status_upper in ('FAILED', 'CANCELLED', 'CANCELED', 'REJECTED'):
            return 'FAILED', message or status
        if status_upper in ('PENDING', 'PROCESSING', 'IN_PROGRESS'):
            return 'PENDING', message or status

        return 'UNKNOWN', message or status


def get_lipila_client() -> LipilaClient:
    return LipilaClient(
        api_key=getattr(settings, 'LIPILA_API_KEY', '') or '',
        base_url=getattr(settings, 'LIPILA_BASE_URL', 'https://api.lipila.dev'),
    )
