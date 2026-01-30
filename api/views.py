from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import get_user_model
from .serializers import (
    UserSerializer,
    PublicUserSerializer,
    UserUpdateSerializer,
    ProfileSerializer,
    MatchSerializer,
    UserRegistrationSerializer,
    ChangePasswordSerializer
)
from accounts.models import CustomUser, Profile
from matches.models import Match

User = get_user_model()


class UserRegistrationView(APIView):
    """
    POST /api/auth/register/
    
    Register a new user and return JWT tokens.
    
    Request body:
    {
        "username": "newuser",
        "email": "user@example.com",
        "password": "securepassword123",
        "password_confirm": "securepassword123"
    }
    
    Response:
    {
        "user": {
            "id": 1,
            "username": "newuser",
            "email": "user@example.com"
        },
        "access": "eyJ0eXAiOiJKV1QiLCJhbGc...",
        "refresh": "eyJ0eXAiOiJKV1QiLCJhbGc..."
    }
    """
    permission_classes = [permissions.AllowAny]
    
    def post(self, request):
        serializer = UserRegistrationSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            
            # Generate JWT tokens
            refresh = RefreshToken.for_user(user)
            
            # Return user data and tokens
            user_serializer = UserSerializer(user)
            return Response({
                'user': user_serializer.data,
                'access': str(refresh.access_token),
                'refresh': str(refresh)
            }, status=status.HTTP_201_CREATED)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ChangePasswordView(APIView):
    """
    POST /api/auth/change-password/
    
    Change user password. Requires authentication.
    
    Request body:
    {
        "old_password": "oldpass123",
        "new_password": "newpass123",
        "new_password_confirm": "newpass123"
    }
    
    Response:
    {
        "message": "Password changed successfully"
    }
    """
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request):
        serializer = ChangePasswordSerializer(
            data=request.data,
            context={'request': request}
        )
        
        if serializer.is_valid():
            serializer.save()
            return Response({
                'message': 'Password changed successfully'
            }, status=status.HTTP_200_OK)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class PasswordResetRequestView(APIView):
    """
    POST /api/auth/password-reset/
    
    Request password reset. Sends reset email if email service is configured.
    
    Request body:
    {
        "email": "user@example.com"
    }
    
    Response:
    {
        "message": "Password reset email sent if account exists"
    }
    
    Note: This is a basic implementation. For production, integrate with
    Django's password reset system or email service.
    """
    permission_classes = [permissions.AllowAny]
    
    def post(self, request):
        email = request.data.get('email')
        
        if not email:
            return Response({
                'error': 'Email is required'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Check if user exists
        try:
            user = User.objects.get(email=email)
            # In production, send password reset email here
            # For now, just return success message
            return Response({
                'message': 'If an account exists with this email, a password reset link has been sent.'
            }, status=status.HTTP_200_OK)
        except User.DoesNotExist:
            # Don't reveal if email exists or not (security best practice)
            return Response({
                'message': 'If an account exists with this email, a password reset link has been sent.'
            }, status=status.HTTP_200_OK)


class MeView(generics.RetrieveUpdateAPIView):
    """
    GET /api/me/
    PUT /api/me/
    PATCH /api/me/
    
    Get or update current authenticated user information.
    
    GET: Returns current user data
    PUT/PATCH: Updates current user (username, email, first_name, last_name)
    """
    permission_classes = [permissions.IsAuthenticated]
    
    def get_serializer_class(self):
        if self.request.method in ['PUT', 'PATCH']:
            return UserUpdateSerializer
        return UserSerializer

    def get_object(self):
        return self.request.user


class UserListView(generics.ListAPIView):
    """
    GET /api/users/
    
    List all users. Admin and staff only.
    
    Returns public profile information for all users.
    Supports pagination.
    """
    serializer_class = PublicUserSerializer
    permission_classes = [permissions.IsAdminUser]
    queryset = User.objects.all().order_by('-date_joined')
    
    def get_queryset(self):
        """Filter queryset if needed (e.g., search by username)"""
        queryset = super().get_queryset()
        username = self.request.query_params.get('username', None)
        if username:
            queryset = queryset.filter(username__icontains=username)
        return queryset


class UserDetailView(generics.RetrieveAPIView):
    """
    GET /api/users/{id}/
    
    Get public profile information for a specific user.
    
    Returns limited user information (no email, no sensitive data).
    Public endpoint (no authentication required).
    """
    serializer_class = PublicUserSerializer
    permission_classes = [permissions.AllowAny]
    queryset = User.objects.all()
    lookup_field = 'id'


class ProfileView(generics.RetrieveUpdateAPIView):
    """
    GET /api/me/profile/
    PUT /api/me/profile/
    PATCH /api/me/profile/
    
    Get or update current user's profile (first_name, last_name).
    
    GET: Returns current user's profile
    PUT/PATCH: Updates profile fields
    """
    serializer_class = ProfileSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_object(self):
        """Get or create profile for current user"""
        profile, created = Profile.objects.get_or_create(user=self.request.user)
        return profile


class MyMatchesView(generics.ListAPIView):
    """
    GET /api/my-matches/
    
    Get all matches where current user is creator or joiner.
    """
    serializer_class = MatchSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        return Match.objects.filter(creator=user) | Match.objects.filter(joiner=user)
