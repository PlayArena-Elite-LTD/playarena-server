"""Low-level ZynlePay JSON API client."""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict

import requests


class ZynleService:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        merchant_id: str,
        api_id: str = '',
        channel: str = 'momo',
        deposit_method: str = 'runBillPayment',
        withdraw_method: str = 'runPayToEwallet',
        status_method: str = 'checkPaymentStatus',
        timeout: int = 60,
    ) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.api_id = api_id
        self.merchant_id = merchant_id
        self.channel = channel
        self.deposit_method = deposit_method
        self.withdraw_method = withdraw_method
        self.status_method = status_method
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return all((self.base_url, self.api_key, self.api_id, self.merchant_id))

    def momo_deposit(
        self,
        *,
        sender_id: str,
        amount: Decimal,
        reference_no: str,
    ) -> Dict[str, Any]:
        return self._post({
            'auth': self._auth(),
            'data': {
                'method': self.deposit_method,
                'sender_id': sender_id,
                'reference_no': reference_no,
                'amount': str(amount),
            },
        })

    def momo_withdraw(
        self,
        *,
        receiver_id: str,
        amount: Decimal,
        reference_no: str,
    ) -> Dict[str, Any]:
        return self._post({
            'auth': self._auth(),
            'data': {
                'method': self.withdraw_method,
                'receiver_id': receiver_id,
                'reference_no': reference_no,
                'amount': str(amount),
            },
        })

    def check_payment_status(self, reference_no: str) -> Dict[str, Any]:
        return self._post({
            'auth': self._auth(),
            'data': {
                'method': self.status_method,
                'reference_no': reference_no,
            },
        })

    def _auth(self) -> Dict[str, str]:
        return {
            'merchant_id': self.merchant_id,
            'api_id': self.api_id,
            'api_key': self.api_key,
            'channel': self.channel,
        }

    def _post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        response = requests.post(
            self.base_url,
            json=payload,
            headers={'Content-Type': 'application/json', 'Accept': '*/*'},
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise requests.RequestException('Zynle returned a non-object JSON response')
        # Sandbox responses may wrap the documented response body in
        # {"response": {...}}.
        wrapped = data.get('response')
        return wrapped if isinstance(wrapped, dict) else data
