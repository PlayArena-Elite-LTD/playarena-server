"""
Payment gateway abstraction — swappable providers (Lipila active).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class PaymentInitResult:
    success: bool
    provider: str
    provider_transaction_id: Optional[str] = None
    payment_reference: Optional[str] = None
    payment_status: str = 'Pending'  # Pending | Successful | Failed
    payment_url: Optional[str] = None
    message: str = ''
    failure_reason: Optional[str] = None
    raw_response: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PaymentVerifyResult:
    success: bool
    payment_status: str  # Pending | Successful | Failed
    provider_transaction_id: Optional[str] = None
    message: str = ''
    raw_response: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WebhookResult:
    processed: bool
    payment_status: Optional[str] = None
    deposit_id: Optional[int] = None
    message: str = ''
    raw_payload: Dict[str, Any] = field(default_factory=dict)


class PaymentGateway(ABC):
    """Base contract for server-side payment providers."""

    provider_name: str = 'unknown'

    @abstractmethod
    def initiate_payment(
        self,
        deposit,
        request,
        *,
        mobile_number: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> PaymentInitResult:
        """Start payment server-to-server; never trust frontend success."""

    @abstractmethod
    def verify_payment(self, deposit) -> PaymentVerifyResult:
        """Poll provider for authoritative payment status."""

    @abstractmethod
    def handle_webhook(self, request) -> WebhookResult:
        """Process provider webhook; must be idempotent."""

    def refund_payment(self, deposit, amount=None) -> Dict[str, Any]:
        """Optional stub for future refund support."""
        return {
            'success': False,
            'message': f'Refunds are not implemented for {self.provider_name}',
        }
