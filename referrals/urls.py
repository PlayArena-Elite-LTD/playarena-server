from django.urls import path

from .views import (
    ReferralApplyView,
    ReferralLedgerView,
    ReferralMeView,
    ReferralWalletView,
    ReferralWithdrawalView,
    ReferredPlayersView,
)

urlpatterns = [
    path("apply/", ReferralApplyView.as_view(), name="api_referral_apply"),
    path("me/", ReferralMeView.as_view(), name="api_referral_me"),
    path("wallet/", ReferralWalletView.as_view(), name="api_referral_wallet"),
    path("ledger/", ReferralLedgerView.as_view(), name="api_referral_ledger"),
    path("referred/", ReferredPlayersView.as_view(), name="api_referral_referred"),
    path("withdrawals/", ReferralWithdrawalView.as_view(), name="api_referral_withdrawals"),
]
