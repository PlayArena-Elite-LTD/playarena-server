from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth import get_user_model
from accounts.models import CustomUser, Profile
from matches.models import Match
from wallet.models import Wallet, Transaction, Deposit, Withdrawal

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
    class Meta:
        model = Deposit
        fields = ['amount', 'payment_method']

    def create(self, validated_data):
        request = self.context.get('request')
        user = request.user
        wallet, _created = Wallet.objects.get_or_create(user=user)
        ip_address = request.META.get('REMOTE_ADDR')
        user_agent = request.META.get('HTTP_USER_AGENT', '')[:500]

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
        wallet, _created = Wallet.objects.get_or_create(user=user)
        ip_address = request.META.get('REMOTE_ADDR')
        user_agent = request.META.get('HTTP_USER_AGENT', '')[:500]

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
        withdrawal.save()
        return withdrawal


class MatchSerializer(serializers.ModelSerializer):
    class Meta:
        model = Match
        fields = ['id', 'game', 'device', 'amount', 'status', 'created_at']


