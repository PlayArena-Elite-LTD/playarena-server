"""URL routes for the admin/support panel API, mounted at /api/panel/."""
from django.urls import path
from . import panel_views as v

urlpatterns = [
    path('stats/', v.PanelStatsView.as_view(), name='panel_api_stats'),
    path('stats/trend/', v.PanelStatsTrendView.as_view(), name='panel_api_stats_trend'),
    path('payment-gateway/', v.PanelPaymentGatewayView.as_view(), name='panel_api_payment_gateway'),

    # Users
    path('users/', v.PanelUserListView.as_view(), name='panel_api_users'),
    path('users/<int:user_id>/toggle/', v.PanelUserToggleView.as_view(), name='panel_api_user_toggle'),

    # Matches
    path('matches/', v.PanelMatchListView.as_view(), name='panel_api_matches'),
    path('matches/<int:match_id>/', v.PanelMatchDetailView.as_view(), name='panel_api_match_detail'),
    path('evidence/<int:evidence_id>/verify/', v.PanelVerifyEvidenceView.as_view(), name='panel_api_evidence_verify'),

    # Wallets / transactions
    path('wallets/', v.PanelWalletListView.as_view(), name='panel_api_wallets'),
    path('wallets/<int:wallet_id>/reconcile/', v.PanelWalletReconcileView.as_view(), name='panel_api_wallet_reconcile'),
    path('transactions/', v.PanelTransactionListView.as_view(), name='panel_api_transactions'),

    # Deposits
    path('deposits/', v.PanelDepositListView.as_view(), name='panel_api_deposits'),
    path('deposits/<int:deposit_id>/complete/', v.PanelDepositCompleteView.as_view(), name='panel_api_deposit_complete'),

    # Withdrawals
    path('withdrawals/', v.PanelWithdrawalListView.as_view(), name='panel_api_withdrawals'),
    path('withdrawals/<int:withdrawal_id>/action/', v.PanelWithdrawalActionView.as_view(), name='panel_api_withdrawal_action'),

    # Disputes
    path('disputes/', v.PanelDisputeListView.as_view(), name='panel_api_disputes'),
    path('disputes/stats/', v.PanelDisputeStatsView.as_view(), name='panel_api_dispute_stats'),
    path('disputes/<int:dispute_id>/', v.PanelDisputeDetailView.as_view(), name='panel_api_dispute_detail'),
    path('disputes/<int:dispute_id>/attend/', v.PanelDisputeAttendView.as_view(), name='panel_api_dispute_attend'),
    path('disputes/<int:dispute_id>/resolve/', v.PanelDisputeResolveView.as_view(), name='panel_api_dispute_resolve'),
    path('disputes/<int:dispute_id>/escalate/', v.PanelDisputeEscalateView.as_view(), name='panel_api_dispute_escalate'),
    path('disputes/<int:dispute_id>/suspend-user/', v.PanelDisputeSuspendUserView.as_view(), name='panel_api_dispute_suspend'),
]
