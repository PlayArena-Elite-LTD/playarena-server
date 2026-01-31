from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from .views import (
    MeView,
    ProfileView,
    MyMatchesView,
    MatchListView,
    MatchDetailView,
    UserListView,
    UserDetailView,
    UserRegistrationView,
    ChangePasswordView,
    PasswordResetRequestView,
    WalletDetailView,
    TransactionHistoryView,
    DepositCreateView,
    WithdrawalCreateView
)


urlpatterns = [
    # Authentication endpoints
    path('auth/register/', UserRegistrationView.as_view(), name='api_register'),
    path('auth/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('auth/change-password/', ChangePasswordView.as_view(), name='api_change_password'),
    path('auth/password-reset/', PasswordResetRequestView.as_view(), name='api_password_reset'),

    # User endpoints
    path('me/', MeView.as_view(), name='api_me'),
    path('me/profile/', ProfileView.as_view(), name='api_profile'),
    path('users/', UserListView.as_view(), name='api_user_list'),
    path('users/<int:id>/', UserDetailView.as_view(), name='api_user_detail'),

    # Match endpoints
    path('my-matches/', MyMatchesView.as_view(), name='api_my_matches'),
    path('matches/', MatchListView.as_view(), name='api_match_list'),
    path('matches/<int:id>/', MatchDetailView.as_view(), name='api_match_detail'),

    # Wallet endpoints
    path('wallet/', WalletDetailView.as_view(), name='api_wallet'),
    path('wallet/transactions/', TransactionHistoryView.as_view(), name='api_wallet_transactions'),
    path('wallet/deposit/', DepositCreateView.as_view(), name='api_wallet_deposit'),
    path('wallet/withdraw/', WithdrawalCreateView.as_view(), name='api_wallet_withdraw'),
]


