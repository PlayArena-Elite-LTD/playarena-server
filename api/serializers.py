from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth import get_user_model
from accounts.models import CustomUser, Profile
from matches.models import Match
from panel.models import Dispute
from messenger.models import Message, ReadMessage
from alert.models import Notification, ReadNotification

User = get_user_model()


class ProfileSerializer(serializers.ModelSerializer):
    """Serializer for user profile (first_name, last_name)"""
    class Meta:
        model = Profile
        fields = ['first_name', 'last_name']


class UserSerializer(serializers.ModelSerializer):
    """Enhanced user serializer with profile data"""
    profile = ProfileSerializer(read_only=True)
    
    class Meta:
        model = CustomUser
        fields = [
            'id', 
            'username', 
            'email', 
            'date_joined', 
            'is_support_staff',
            'is_active',
            'profile'
        ]
        read_only_fields = ['id', 'date_joined', 'is_support_staff']


class PublicUserSerializer(serializers.ModelSerializer):
    """Public user serializer for viewing other users (limited fields)"""
    profile = ProfileSerializer(read_only=True)
    
    class Meta:
        model = CustomUser
        fields = [
            'id',
            'username',
            'date_joined',
            'profile'
        ]
        read_only_fields = ['id', 'username', 'date_joined']


class UserRegistrationSerializer(serializers.ModelSerializer):
    """Serializer for user registration with password validation"""
    password = serializers.CharField(
        write_only=True,
        required=True,
        validators=[validate_password],
        style={'input_type': 'password'}
    )
    password_confirm = serializers.CharField(
        write_only=True,
        required=True,
        style={'input_type': 'password'}
    )
    
    class Meta:
        model = CustomUser
        fields = ['username', 'email', 'password', 'password_confirm']
        extra_kwargs = {
            'email': {'required': True},
            'username': {'required': True}
        }
    
    def validate_email(self, value):
        """Validate email uniqueness"""
        if CustomUser.objects.filter(email=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value
    
    def validate_username(self, value):
        """Validate username uniqueness"""
        if CustomUser.objects.filter(username=value).exists():
            raise serializers.ValidationError("A user with this username already exists.")
        return value
    
    def validate(self, attrs):
        """Validate that passwords match"""
        if attrs['password'] != attrs['password_confirm']:
            raise serializers.ValidationError({
                "password_confirm": "Password fields didn't match."
            })
        return attrs
    
    def create(self, validated_data):
        """Create user with hashed password"""
        validated_data.pop('password_confirm')
        password = validated_data.pop('password')
        user = CustomUser.objects.create(**validated_data)
        user.set_password(password)
        user.save()
        return user


class UserUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating user information (excludes password)"""
    email = serializers.EmailField(required=False)
    
    class Meta:
        model = CustomUser
        fields = ['username', 'email', 'first_name', 'last_name']
        extra_kwargs = {
            'username': {'required': False}
        }
    
    def validate_email(self, value):
        """Validate email uniqueness (excluding current user)"""
        user = self.instance
        if CustomUser.objects.filter(email=value).exclude(pk=user.pk).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value
    
    def validate_username(self, value):
        """Validate username uniqueness (excluding current user)"""
        user = self.instance
        if CustomUser.objects.filter(username=value).exclude(pk=user.pk).exists():
            raise serializers.ValidationError("A user with this username already exists.")
        return value
    
    def update(self, instance, validated_data):
        """Update user and profile"""
        # Update user fields
        instance.username = validated_data.get('username', instance.username)
        instance.email = validated_data.get('email', instance.email)
        instance.save()
        
        # Update profile if first_name or last_name provided
        profile_data = {}
        if 'first_name' in validated_data:
            profile_data['first_name'] = validated_data.pop('first_name')
        if 'last_name' in validated_data:
            profile_data['last_name'] = validated_data.pop('last_name')
        
        if profile_data:
            profile, created = Profile.objects.get_or_create(user=instance)
            for key, value in profile_data.items():
                setattr(profile, key, value)
            profile.save()
        
        return instance


class ChangePasswordSerializer(serializers.Serializer):
    """Serializer for password change"""
    old_password = serializers.CharField(
        required=True,
        write_only=True,
        style={'input_type': 'password'}
    )
    new_password = serializers.CharField(
        required=True,
        write_only=True,
        validators=[validate_password],
        style={'input_type': 'password'}
    )
    new_password_confirm = serializers.CharField(
        required=True,
        write_only=True,
        style={'input_type': 'password'}
    )
    
    def validate_old_password(self, value):
        """Validate old password is correct"""
        user = self.context['request'].user
        if not user.check_password(value):
            raise serializers.ValidationError("Old password is incorrect.")
        return value
    
    def validate(self, attrs):
        """Validate that new passwords match"""
        if attrs['new_password'] != attrs['new_password_confirm']:
            raise serializers.ValidationError({
                "new_password_confirm": "New password fields didn't match."
            })
        return attrs
    
    def save(self):
        """Update user password"""
        user = self.context['request'].user
        user.set_password(self.validated_data['new_password'])
        user.save()
        return user


class MatchSerializer(serializers.ModelSerializer):
    class Meta:
        model = Match
        fields = ['id', 'game', 'device', 'amount', 'status', 'created_at']


class DisputeSerializer(serializers.ModelSerializer):
    """Serializer for Dispute model"""
    match_id = serializers.IntegerField(source='match.id', read_only=True)
    match_game = serializers.SerializerMethodField()
    match_amount = serializers.DecimalField(source='match.amount', max_digits=10, decimal_places=2, read_only=True)
    match_status = serializers.CharField(source='match.status', read_only=True)
    assigned_to_username = serializers.CharField(source='assigned_to.username', read_only=True, allow_null=True)
    creator_username = serializers.CharField(source='match.creator.username', read_only=True)
    joiner_username = serializers.CharField(source='match.joiner.username', read_only=True, allow_null=True)
    
    def get_match_game(self, obj):
        """Get the display name for the match game"""
        return obj.match.get_game_display() if obj.match else None
    
    class Meta:
        model = Dispute
        fields = [
            'id',
            'match_id',
            'match_game',
            'match_amount',
            'match_status',
            'status',
            'created_at',
            'assigned_to',
            'assigned_to_username',
            'resolution_notes',
            'resolved_at',
            'creator_username',
            'joiner_username'
        ]
        read_only_fields = ['id', 'created_at', 'resolved_at']


class DisputeResolutionSerializer(serializers.Serializer):
    """Serializer for resolving disputes"""
    status = serializers.ChoiceField(choices=Dispute.STATUS_CHOICES)
    resolution_notes = serializers.CharField(required=False, allow_blank=True)
    
    def validate_status(self, value):
        """Ensure status is valid"""
        if value not in ['OPEN', 'PENDING', 'RESOLVED']:
            raise serializers.ValidationError("Invalid status choice.")
        return value


class MessageSerializer(serializers.ModelSerializer):
    """Serializer for Message model"""
    sender_username = serializers.CharField(source='sender.username', read_only=True)
    receiver_username = serializers.CharField(source='receiver.username', read_only=True)
    is_read = serializers.SerializerMethodField()
    
    class Meta:
        model = Message
        fields = [
            'id',
            'sender',
            'sender_username',
            'receiver',
            'receiver_username',
            'message',
            'created_at',
            'is_read'
        ]
        read_only_fields = ['id', 'created_at', 'sender']
    
    def get_is_read(self, obj):
        """Check if message is read by receiver"""
        request = self.context.get('request')
        if request and request.user == obj.receiver:
            return ReadMessage.objects.filter(message=obj, receiver=request.user).exists()
        return False


class MessageCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating new messages"""
    class Meta:
        model = Message
        fields = ['receiver', 'message']
    
    def validate_receiver(self, value):
        """Ensure user doesn't message themselves"""
        request = self.context.get('request')
        if request and value == request.user:
            raise serializers.ValidationError("You cannot send messages to yourself.")
        return value


class NotificationSerializer(serializers.ModelSerializer):
    """Serializer for Notification model"""
    is_read = serializers.SerializerMethodField()
    
    class Meta:
        model = Notification
        fields = [
            'id',
            'message',
            'created_at',
            'is_read'
        ]
        read_only_fields = ['id', 'created_at']
    
    def get_is_read(self, obj):
        """Check if notification is read"""
        request = self.context.get('request')
        if request:
            return ReadNotification.objects.filter(
                notification=obj,
                user=request.user
            ).exists()
        return False

