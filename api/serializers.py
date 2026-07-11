from rest_framework import serializers
from decimal import Decimal
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from accounts.models import CustomUser, Profile
from accounts.forms import signup_integrity_error_messages
from matches.models import Match, MatchResult
from wallet.models import Wallet, Transaction, Deposit, Withdrawal
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
        try:
            user = CustomUser.objects.create(**validated_data)
            user.set_password(password)
            user.save()
        except IntegrityError as exc:
            field_errors = signup_integrity_error_messages(exc)
            if field_errors:
                raise serializers.ValidationError(field_errors) from exc
            raise
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


class WalletSerializer(serializers.ModelSerializer):
    """Serializer for wallet summary data"""
    class Meta:
        model = Wallet
        fields = ['id', 'balance']
        read_only_fields = ['id', 'balance']


class TransactionSerializer(serializers.ModelSerializer):
    """Serializer for wallet transactions"""
    class Meta:
        model = Transaction
        fields = [
            'id',
            'amount',
            'transaction_type',
            'description',
            'created_at',
            'related_match',
        ]
        read_only_fields = fields


class DepositCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating deposit requests"""
    mobile_number = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=20,
        help_text='Required for mobile money (Zambian format, e.g. 26097xxxxxxx)',
    )

    class Meta:
        model = Deposit
        fields = ['amount', 'payment_method', 'mobile_number']

    def validate(self, attrs):
        method = attrs.get('payment_method')
        mobile = (attrs.get('mobile_number') or '').strip()
        if method in ('LIPILA_MOMO', 'ZYNLE_MOMO') and not mobile:
            raise serializers.ValidationError({
                'mobile_number': 'Mobile number is required for Mobile Money deposits.',
            })

        from services.payments.factory import get_active_payment_provider
        active_provider = get_active_payment_provider()
        allowed_gateway_method = {
            'lipila': {'LIPILA', 'LIPILA_MOMO'},
            'zynle': {'ZYNLE_MOMO'},
        }.get(active_provider, set())
        if method in {'LIPILA', 'LIPILA_MOMO', 'ZYNLE_MOMO'} and method not in allowed_gateway_method:
            raise serializers.ValidationError({
                'payment_method': f'{method} is not available while {active_provider} is active.',
            })
        attrs['mobile_number'] = mobile
        return attrs

    def create(self, validated_data):
        request = self.context.get('request')
        user = request.user
        wallet, _created = Wallet.objects.get_or_create(user=user)
        ip_address = request.META.get('REMOTE_ADDR')
        user_agent = request.META.get('HTTP_USER_AGENT', '')[:500]

        validated_data.pop('mobile_number', None)
        deposit = Deposit(
            user=user,
            amount=validated_data['amount'],
            payment_method=validated_data['payment_method'],
            status='PENDING',
            wallet=wallet,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        deposit.full_clean()
        deposit.save()
        return deposit


class WithdrawalCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating withdrawal requests"""
    class Meta:
        model = Withdrawal
        fields = ['amount', 'payment_method', 'account_details']

    def create(self, validated_data):
        request = self.context.get('request')
        user = request.user
        ip_address = request.META.get('REMOTE_ADDR')
        user_agent = request.META.get('HTTP_USER_AGENT', '')[:500]

        with transaction.atomic():
            wallet, _created = Wallet.objects.get_or_create(user=user)
            wallet = Wallet.objects.select_for_update().get(pk=wallet.pk)

            withdrawal = Withdrawal(
                user=user,
                amount=validated_data['amount'],
                payment_method=validated_data['payment_method'],
                account_details=validated_data['account_details'],
                status='PENDING',
                wallet=wallet,
                ip_address=ip_address,
                user_agent=user_agent,
            )
            withdrawal.full_clean()

            if wallet.balance < withdrawal.amount:
                raise serializers.ValidationError({
                    'amount': f'Insufficient balance. Your balance is ZMW {wallet.balance:.2f}'
                })

            withdrawal.save()
            wallet.balance -= withdrawal.amount
            wallet.save(update_fields=['balance'])
            Transaction.objects.create(
                wallet=wallet,
                amount=-withdrawal.amount,
                transaction_type='WITHDRAWAL',
                description=f'Withdrawal request - {withdrawal.get_payment_method_display()}',
            )
        return withdrawal


class MatchSerializer(serializers.ModelSerializer):
    """Serializer for match data"""
    class Meta:
        model = Match
        fields = [
            'id',
            'creator',
            'joiner',
            'game',
            'device',
            'privacy',
            'joining_code',
            'amount',
            'winnings',
            'status',
            'winner',
            'created_at',
        ]
        read_only_fields = [
            'id',
            'creator',
            'joiner',
            'joining_code',
            'winnings',
            'status',
            'winner',
            'created_at',
        ]


class MatchResultSerializer(serializers.ModelSerializer):
    """Serializer for match results"""
    class Meta:
        model = MatchResult
        fields = [
            'id',
            'match',
            'creator_submission',
            'creator_submission_time',
            'joiner_submission',
            'joiner_submission_time',
            'submission_round',
        ]
        read_only_fields = [
            'id',
            'match',
            'creator_submission_time',
            'joiner_submission_time',
            'submission_round',
        ]





class MatchCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating a match"""
    class Meta:
        model = Match
        fields = ['game', 'device', 'privacy', 'amount']

    def validate_amount(self, value):
        request = self.context.get('request')
        user = request.user
        wallet, _created = Wallet.objects.get_or_create(user=user)
        if wallet.balance < Decimal(value):
            raise serializers.ValidationError(
                f"Insufficient funds. Your balance (ZMW {wallet.balance}) is less than the match amount (ZMW {value})."
            )
        return value


class MatchJoinSerializer(serializers.Serializer):
    """Serializer for joining a match by code"""
    joining_code = serializers.CharField(max_length=10)

    def validate_joining_code(self, value):
        request = self.context.get('request')
        user = request.user
        try:
            match = Match.objects.get(joining_code=value, status='OPEN')
        except Match.DoesNotExist:
            raise serializers.ValidationError("Invalid match code or the match is no longer available.")

        if match.creator == user:
            raise serializers.ValidationError("You cannot join your own match.")

        wallet, _created = Wallet.objects.get_or_create(user=user)
        if wallet.balance < Decimal(match.amount):
            raise serializers.ValidationError(
                f"Insufficient funds. You need ZMW {match.amount} to join this match."
            )

        self.context['match'] = match
        return value

class MatchResultSubmissionSerializer(serializers.Serializer):
    """Serializer for submitting a match result"""
    submission = serializers.ChoiceField(choices=['WON', 'LOST', 'DRAW'])

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
            'user',
            'message',
            'created_at',
            'is_read'
        ]
        read_only_fields = ['id', 'user', 'created_at']
    
    def get_is_read(self, obj):
        """Check if notification is read"""
        request = self.context.get('request')
        if request:
            return ReadNotification.objects.filter(
                notification=obj,
                user=request.user
            ).exists()
        return False
