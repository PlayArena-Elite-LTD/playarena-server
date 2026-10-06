from django.urls import path

from .views import (
    ReferralApplyView,
    ReferralLedgerView,
    ReferralMeView,
    ReferralWalletView,
    ReferralTransferView,
    ReferredPlayersView,
)

urlpatterns = [
    path("apply/", ReferralApplyView.as_view(), name="api_referral_apply"),
    path("me/", ReferralMeView.as_view(), name="api_referral_me"),
    path("wallet/", ReferralWalletView.as_view(), name="api_referral_wallet"),
    path("ledger/", ReferralLedgerView.as_view(), name="api_referral_ledger"),
    path("referred/", ReferredPlayersView.as_view(), name="api_referral_referred"),
    path("transfers/", ReferralTransferView.as_view(), name="api_referral_transfers"),
]
