from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from .views import MeView, MyMatchesView


urlpatterns = [
    # JWT auth endpoints
    path('auth/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),

    # Basic authenticated API endpoints
    path('me/', MeView.as_view(), name='api_me'),
    path('my-matches/', MyMatchesView.as_view(), name='api_my_matches'),
]


