from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView
)
from .panel_views import ActivePaymentGatewayView
from .views import LeaderboardView
from .views import (
    MeView,
    ProfileView,
    MyMatchesView,
    MatchListView,
    MatchDetailView,
    MatchCreateView,
    MatchJoinView,
    MatchResultSubmitView,
    MatchCancelView,
    OrganisationDirectoryListView,
    OrganisationJoinRequestView,
    OrganisationLoginView,
    OrganisationPasswordResetRequestView,
    OrganisationPasswordResetConfirmView,
    OrganisationMeView,
    OrganisationMembershipApproveView,
    OrganisationMembershipRejectView,
    OrganisationMembershipRequestListView,
    OrganisationRegistrationView,
    OrganisationTournamentListCreateView,
    OrganisationTournamentRegistrationsView,
    OrganisationTournamentPrizesView,
    OrganisationTournamentStandingsView,
    OrganisationTournamentLockView,
    OrganisationTournamentPayoutsView,
    OrganisationTournamentPayoutRetryView,
    OrganisationTournamentBracketView,
    OrganisationTournamentManualMatchView,
    OrganisationTournamentMatchConfirmView,
    OrganisationTournamentTableView,
    OrganisationTournamentLifecycleView,
    OrganisationTournamentExtendRegistrationView,
    WithdrawalListView,
    PlayerTournamentStandingsView,
    PlayerTournamentBracketView,
    PlayerTournamentMatchReportView,
    PlayerTournamentTableView,
    PlayerTournamentListView,
    MyTournamentsView,
    TournamentJoinView,
    TournamentLeaveView,
    UserListView,
    UserDetailView,
    UserRegistrationView,
    ChangePasswordView,
    PasswordResetRequestView,
    WalletDetailView,
    TransactionHistoryView,
    DepositCreateView,
    WithdrawalCreateView,
    PaymentStatusView,
    LipilaWebhookView,
    ZynleWebhookView,
    DisputeViewSet,
    MessageViewSet,
    NotificationViewSet
)


# Create router for ViewSets
router = DefaultRouter()
router.register(r'disputes', DisputeViewSet, basename='dispute')
router.register(r'messages', MessageViewSet, basename='message')
router.register(r'notifications', NotificationViewSet, basename='notification')

urlpatterns = [
    # Referral program
    path('referrals/', include('referrals.urls')),
    # API Schema endpoints (Swagger/OpenAPI)
    path('schema/', SpectacularAPIView.as_view(), name='schema'),
    path('schema/swagger-ui/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('schema/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
    
    # Authentication endpoints
    path('auth/register/', UserRegistrationView.as_view(), name='api_register'),
    path('auth/organisations/register/', OrganisationRegistrationView.as_view(), name='api_organisation_register'),
    path('auth/organisations/login/', OrganisationLoginView.as_view(), name='api_organisation_login'),
    path('auth/organisations/password-reset/', OrganisationPasswordResetRequestView.as_view(), name='api_organisation_password_reset'),
    path('auth/organisations/password-reset/confirm/', OrganisationPasswordResetConfirmView.as_view(), name='api_organisation_password_reset_confirm'),
    path('auth/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('auth/change-password/', ChangePasswordView.as_view(), name='api_change_password'),
    path('auth/password-reset/', PasswordResetRequestView.as_view(), name='api_password_reset'),

    # User endpoints
    path('me/', MeView.as_view(), name='api_me'),
    path('me/profile/', ProfileView.as_view(), name='api_profile'),
    path('users/', UserListView.as_view(), name='api_user_list'),
    path('users/<int:id>/', UserDetailView.as_view(), name='api_user_detail'),
    path('organisations/', OrganisationDirectoryListView.as_view(), name='api_organisation_list'),
    path('organisations/<int:id>/request-join/', OrganisationJoinRequestView.as_view(), name='api_organisation_request_join'),
    path('organisations/me/', OrganisationMeView.as_view(), name='api_organisation_me'),
    path('organisations/tournaments/', OrganisationTournamentListCreateView.as_view(), name='api_organisation_tournaments'),
    path('organisations/tournaments/<int:id>/registrations/', OrganisationTournamentRegistrationsView.as_view(), name='api_organisation_tournament_registrations'),
    path('organisations/tournaments/<int:id>/prizes/', OrganisationTournamentPrizesView.as_view(), name='api_organisation_tournament_prizes'),
    path('organisations/tournaments/<int:id>/standings/', OrganisationTournamentStandingsView.as_view(), name='api_organisation_tournament_standings'),
    path('organisations/tournaments/<int:id>/lock/', OrganisationTournamentLockView.as_view(), name='api_organisation_tournament_lock'),
    path('organisations/tournaments/<int:id>/payouts/', OrganisationTournamentPayoutsView.as_view(), name='api_organisation_tournament_payouts'),
    path('organisations/tournaments/<int:id>/payouts/<int:payout_id>/retry/', OrganisationTournamentPayoutRetryView.as_view(), name='api_organisation_tournament_payout_retry'),
    path('organisations/tournaments/<int:id>/bracket/', OrganisationTournamentBracketView.as_view(), name='api_organisation_tournament_bracket'),
    path('organisations/tournaments/<int:id>/matches/', OrganisationTournamentManualMatchView.as_view(), name='api_organisation_tournament_manual_match'),
    path('organisations/tournaments/<int:id>/matches/<int:match_id>/confirm/', OrganisationTournamentMatchConfirmView.as_view(), name='api_organisation_tournament_match_confirm'),
    path('organisations/tournaments/<int:id>/table/', OrganisationTournamentTableView.as_view(), name='api_organisation_tournament_table'),
    path('organisations/tournaments/<int:id>/lifecycle/', OrganisationTournamentLifecycleView.as_view(), name='api_organisation_tournament_lifecycle'),
    path('organisations/tournaments/<int:id>/extend-registration/', OrganisationTournamentExtendRegistrationView.as_view(), name='api_organisation_tournament_extend_registration'),
    path('organisations/membership-requests/', OrganisationMembershipRequestListView.as_view(), name='api_organisation_membership_requests'),
    path('organisations/membership-requests/<int:id>/approve/', OrganisationMembershipApproveView.as_view(), name='api_organisation_membership_approve'),
    path('organisations/membership-requests/<int:id>/reject/', OrganisationMembershipRejectView.as_view(), name='api_organisation_membership_reject'),
    path('player/tournaments/', PlayerTournamentListView.as_view(), name='api_player_tournaments'),
    path('player/tournaments/mine/', MyTournamentsView.as_view(), name='api_player_tournaments_mine'),
    path('player/tournaments/<int:id>/join/', TournamentJoinView.as_view(), name='api_player_tournament_join'),
    path('player/tournaments/<int:id>/leave/', TournamentLeaveView.as_view(), name='api_player_tournament_leave'),
    path('player/tournaments/<int:id>/standings/', PlayerTournamentStandingsView.as_view(), name='api_player_tournament_standings'),
    path('player/tournaments/<int:id>/bracket/', PlayerTournamentBracketView.as_view(), name='api_player_tournament_bracket'),
    path('player/tournaments/<int:id>/matches/<int:match_id>/report/', PlayerTournamentMatchReportView.as_view(), name='api_player_tournament_match_report'),
    path('player/tournaments/<int:id>/table/', PlayerTournamentTableView.as_view(), name='api_player_tournament_table'),

    # Match endpoints
    path('my-matches/', MyMatchesView.as_view(), name='api_my_matches'),
    path('matches/', MatchListView.as_view(), name='api_match_list'),
    path('matches/<int:id>/', MatchDetailView.as_view(), name='api_match_detail'),
    path('matches/create/', MatchCreateView.as_view(), name='api_match_create'),
    path('matches/join/', MatchJoinView.as_view(), name='api_match_join'),
    path('matches/<int:id>/submit-result/', MatchResultSubmitView.as_view(), name='api_match_submit_result'),
    path('matches/<int:id>/cancel/', MatchCancelView.as_view(), name='api_match_cancel'),

    # Wallet endpoints
    path('wallet/', WalletDetailView.as_view(), name='api_wallet'),
    path('wallet/transactions/', TransactionHistoryView.as_view(), name='api_wallet_transactions'),
    path('wallet/deposit/', DepositCreateView.as_view(), name='api_wallet_deposit'),
    path('wallet/withdraw/', WithdrawalCreateView.as_view(), name='api_wallet_withdraw'),
    path('wallet/withdrawals/', WithdrawalListView.as_view(), name='api_wallet_withdrawals'),
    path('payment/status/<int:order_id>/', PaymentStatusView.as_view(), name='api_payment_status'),
    path('payment/gateway/', ActivePaymentGatewayView.as_view(), name='api_active_gateway'),
    path('leaderboard/', LeaderboardView.as_view(), name='api_leaderboard'),
    path('payments/lipila/webhook/', LipilaWebhookView.as_view(), name='api_lipila_webhook'),
    path('payments/zynle/webhook/', ZynleWebhookView.as_view(), name='api_zynle_webhook'),
    
    # Admin/support panel API
    path('panel/', include('api.panel_urls')),

    # Include router URLs (disputes, messages, notifications)
    path('', include(router.urls)),
]
