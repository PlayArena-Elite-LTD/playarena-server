from rest_framework import generics, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.db.models import Q
from django.shortcuts import get_object_or_404
from .serializers import (
    UserSerializer,
    PublicUserSerializer,
    UserUpdateSerializer,
    ProfileSerializer,
    MatchSerializer,
    UserRegistrationSerializer,
    ChangePasswordSerializer,
    DisputeSerializer,
    DisputeResolutionSerializer,
    MessageSerializer,
    MessageCreateSerializer,
    NotificationSerializer
)
from accounts.models import CustomUser, Profile
from matches.models import Match
from panel.models import Dispute
from messenger.models import Message, ReadMessage
from alert.models import Notification, ReadNotification

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


class DisputeViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing disputes.
    
    list: GET /api/disputes/ - List all disputes (support staff: all, users: own)
    retrieve: GET /api/disputes/{id}/ - Get dispute detail
    resolve: POST /api/disputes/{id}/resolve/ - Resolve a dispute (support staff only)
    """
    serializer_class = DisputeSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        """Filter disputes based on user role"""
        user = self.request.user
        
        # Support staff can see all disputes
        if user.is_support_staff or user.is_staff:
            queryset = Dispute.objects.all()
        else:
            # Regular users can only see disputes for their matches
            queryset = Dispute.objects.filter(
                match__creator=user
            ) | Dispute.objects.filter(
                match__joiner=user
            )
        
        # Filter by status if provided
        status_filter = self.request.query_params.get('status', None)
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        
        return queryset.order_by('-created_at')
    
    def get_permissions(self):
        """Override permissions for specific actions"""
        if self.action == 'resolve':
            # Only support staff can resolve disputes
            return [permissions.IsAuthenticated(), permissions.IsAdminUser()]
        # Regular users can list and retrieve their own disputes
        return [permissions.IsAuthenticated()]
    
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAdminUser])
    def resolve(self, request, pk=None):
        """
        POST /api/disputes/{id}/resolve/
        
        Resolve a dispute. Only support staff can resolve disputes.
        
        Request body:
        {
            "status": "RESOLVED",
            "resolution_notes": "Dispute resolved in favor of creator"
        }
        """
        dispute = self.get_object()
        serializer = DisputeResolutionSerializer(data=request.data)
        
        if serializer.is_valid():
            dispute.status = serializer.validated_data['status']
            dispute.resolution_notes = serializer.validated_data.get('resolution_notes', '')
            
            if dispute.status == 'RESOLVED':
                dispute.resolved_at = timezone.now()
            
            dispute.save()
            
            # Create notification for match participants
            match = dispute.match
            participants = [match.creator]
            if match.joiner:
                participants.append(match.joiner)
            
            for participant in participants:
                Notification.objects.create(
                    user=participant,
                    message=f"Dispute for match {dispute.match.joining_code} has been {dispute.get_status_display().lower()}."
                )
            
            return Response(
                DisputeSerializer(dispute).data,
                status=status.HTTP_200_OK
            )
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class MessageViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing messages.
    
    list: GET /api/messages/ - List all messages (sent/received)
    create: POST /api/messages/ - Send a new message
    retrieve: GET /api/messages/{id}/ - Get message detail
    conversations: GET /api/messages/conversations/ - List all conversations
    conversation: GET /api/messages/conversation/{user_id}/ - Get conversation with a user
    """
    permission_classes = [permissions.IsAuthenticated]
    
    def get_serializer_class(self):
        """Use different serializers for different actions"""
        if self.action == 'create':
            return MessageCreateSerializer
        return MessageSerializer
    
    def get_queryset(self):
        """Get messages where user is sender or receiver"""
        user = self.request.user
        return (Message.objects.filter(sender=user) | 
                Message.objects.filter(receiver=user)).order_by('-created_at')
    
    def perform_create(self, serializer):
        """Set sender to current user and create notification"""
        serializer.save(sender=self.request.user)
        
        receiver = serializer.validated_data['receiver']
        Notification.objects.create(
            user=receiver,
            message=f"You have a new message from {self.request.user.username}"
        )
    
    @action(detail=False, methods=['get'])
    def conversations(self, request):
        """
        GET /api/messages/conversations/
        
        List all conversations (users you've messaged with).
        Returns list of users with latest message and unread count.
        """
        user = request.user
        User = get_user_model()
        
        # Get all users the current user has exchanged messages with
        conversations = User.objects.filter(
            Q(sent_messages__receiver=user) | 
            Q(received_messages__sender=user)
        ).distinct().exclude(id=user.id)
        
        conversation_data = []
        for other_user in conversations:
            # Get latest message
            latest_message = Message.objects.filter(
                (Q(sender=user) & Q(receiver=other_user)) |
                (Q(sender=other_user) & Q(receiver=user))
            ).order_by('-created_at').first()
            
            # Count unread messages
            unread_count = Message.objects.filter(
                sender=other_user,
                receiver=user
            ).exclude(
                id__in=ReadMessage.objects.filter(
                    receiver=user
                ).values_list('message_id', flat=True)
            ).count()
            
            conversation_data.append({
                'user_id': other_user.id,
                'username': other_user.username,
                'latest_message': MessageSerializer(
                    latest_message,
                    context={'request': request}
                ).data if latest_message else None,
                'unread_count': unread_count
            })
        
        return Response(conversation_data, status=status.HTTP_200_OK)
    
    @action(detail=False, methods=['get'], url_path='conversation/(?P<user_id>[^/.]+)')
    def conversation(self, request, user_id=None):
        """
        GET /api/messages/conversation/{user_id}/
        
        Get all messages in a conversation with a specific user.
        Marks messages as read when viewed.
        """
        User = get_user_model()
        other_user = get_object_or_404(User, id=user_id)
        
        # Get all messages between these two users
        messages = Message.objects.filter(
            (Q(sender=request.user) & Q(receiver=other_user)) |
            (Q(sender=other_user) & Q(receiver=request.user))
        ).order_by('created_at')
        
        # Mark all received messages as read
        unread_messages = Message.objects.filter(
            sender=other_user,
            receiver=request.user
        ).exclude(
            id__in=ReadMessage.objects.filter(
                receiver=request.user
            ).values_list('message_id', flat=True)
        )
        
        for msg in unread_messages:
            ReadMessage.objects.get_or_create(
                message=msg,
                receiver=request.user
            )
        
        serializer = MessageSerializer(messages, many=True, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)


class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for managing notifications.
    
    list: GET /api/notifications/ - List all notifications for current user
    retrieve: GET /api/notifications/{id}/ - Get notification detail
    mark_read: POST /api/notifications/{id}/mark-read/ - Mark notification as read
    mark_all_read: POST /api/notifications/mark-all-read/ - Mark all notifications as read
    unread_count: GET /api/notifications/unread-count/ - Get unread notification count
    """
    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        """Get notifications for current user only"""
        return Notification.objects.filter(
            user=self.request.user
        ).order_by('-created_at')
    
    @action(detail=True, methods=['post'])
    def mark_read(self, request, pk=None):
        """
        POST /api/notifications/{id}/mark-read/
        
        Mark a specific notification as read.
        """
        notification = self.get_object()
        
        # Ensure user can only mark their own notifications as read
        if notification.user != request.user:
            return Response(
                {'error': 'You can only mark your own notifications as read.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        ReadNotification.objects.get_or_create(
            notification=notification,
            user=request.user
        )
        
        return Response(
            {'message': 'Notification marked as read.'},
            status=status.HTTP_200_OK
        )
    
    @action(detail=False, methods=['post'])
    def mark_all_read(self, request):
        """
        POST /api/notifications/mark-all-read/
        
        Mark all notifications for current user as read.
        """
        unread_notifications = Notification.objects.filter(
            user=request.user
        ).exclude(
            id__in=ReadNotification.objects.filter(
                user=request.user
            ).values_list('notification_id', flat=True)
        )
        
        for notification in unread_notifications:
            ReadNotification.objects.get_or_create(
                notification=notification,
                user=request.user
            )
        
        return Response(
            {'message': f'{unread_notifications.count()} notifications marked as read.'},
            status=status.HTTP_200_OK
        )
    
    @action(detail=False, methods=['get'])
    def unread_count(self, request):
        """
        GET /api/notifications/unread-count/
        
        Get count of unread notifications for current user.
        """
        unread_count = Notification.objects.filter(
            user=request.user
        ).exclude(
            id__in=ReadNotification.objects.filter(
                user=request.user
            ).values_list('notification_id', flat=True)
        ).count()
        
        return Response(
            {'unread_count': unread_count},
            status=status.HTTP_200_OK
        )
