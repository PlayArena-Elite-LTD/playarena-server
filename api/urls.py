from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView
)
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
    UserListView,
    UserDetailView,
    UserRegistrationView,
    ChangePasswordView,
    PasswordResetRequestView,
    WalletDetailView,
    TransactionHistoryView,
    DepositCreateView,
    WithdrawalCreateView,
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
    # API Schema endpoints (Swagger/OpenAPI)
    path('schema/', SpectacularAPIView.as_view(), name='schema'),
    path('schema/swagger-ui/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('schema/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
    
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
    path('matches/create/', MatchCreateView.as_view(), name='api_match_create'),
    path('matches/join/', MatchJoinView.as_view(), name='api_match_join'),
    path('matches/<int:id>/submit-result/', MatchResultSubmitView.as_view(), name='api_match_submit_result'),
    path('matches/<int:id>/cancel/', MatchCancelView.as_view(), name='api_match_cancel'),

    # Wallet endpoints
    path('wallet/', WalletDetailView.as_view(), name='api_wallet'),
    path('wallet/transactions/', TransactionHistoryView.as_view(), name='api_wallet_transactions'),
    path('wallet/deposit/', DepositCreateView.as_view(), name='api_wallet_deposit'),
    path('wallet/withdraw/', WithdrawalCreateView.as_view(), name='api_wallet_withdraw'),
    
    # Include router URLs (disputes, messages, notifications)
    path('', include(router.urls)),
]


