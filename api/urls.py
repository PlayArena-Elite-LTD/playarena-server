from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from .views import (
    MeView,
    MyMatchesView,
    UserRegistrationView,
    ChangePasswordView,
    PasswordResetRequestView
)


urlpatterns = [
    # Authentication endpoints
    path('auth/register/', UserRegistrationView.as_view(), name='api_register'),
    path('auth/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('auth/change-password/', ChangePasswordView.as_view(), name='api_change_password'),
    path('auth/password-reset/', PasswordResetRequestView.as_view(), name='api_password_reset'),

    # Basic authenticated API endpoints
    path('me/', MeView.as_view(), name='api_me'),
    path('my-matches/', MyMatchesView.as_view(), name='api_my_matches'),
]


