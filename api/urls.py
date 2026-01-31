from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from .views import (
    MeView,
    ProfileView,
    MyMatchesView,
    UserListView,
    UserDetailView,
    UserRegistrationView,
    ChangePasswordView,
    PasswordResetRequestView,
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
    
    # Include router URLs (disputes, messages, notifications)
    path('', include(router.urls)),
]


