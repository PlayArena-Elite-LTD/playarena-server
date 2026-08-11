from rest_framework import serializers
from decimal import Decimal
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth import authenticate, get_user_model
from django.utils.text import slugify
from django.db import IntegrityError, transaction
from accounts.models import CustomUser, Organisation, OrganisationMembership, Profile
from accounts.forms import signup_integrity_error_messages
from matches.models import Match, MatchResult, Tournament, TournamentRegistration
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
    is_organiser = serializers.SerializerMethodField()
    
    class Meta:
        model = CustomUser
        fields = [
            'id',
            'username',
            'email',
            'date_joined',
            'is_support_staff',
            'is_staff',
            'is_superuser',
            'is_active',
            'profile',
            'is_organiser'
        ]
        read_only_fields = ['id', 'date_joined', 'is_support_staff', 'is_staff', 'is_superuser', 'is_organiser']

    def get_is_organiser(self, obj):
        return hasattr(obj, 'organisation')


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


class OrganisationSerializer(serializers.ModelSerializer):
    """Serializer for organisation account details."""
    organisation_type_label = serializers.CharField(source='get_organisation_type_display', read_only=True)
    owner = UserSerializer(read_only=True)

    class Meta:
        model = Organisation
        fields = [
            'id',
            'name',
            'contact_name',
            'email',
            'phone',
            'organisation_type',
            'organisation_type_label',
            'city',
            'is_verified',
            'created_at',
            'updated_at',
            'owner',
        ]
        read_only_fields = ['id', 'is_verified', 'created_at', 'updated_at', 'owner']


class OrganisationDirectorySerializer(serializers.ModelSerializer):
    """Organisation listing for players, including their membership state."""
    organisation_type_label = serializers.CharField(source='get_organisation_type_display', read_only=True)
    membership_status = serializers.SerializerMethodField()
    membership_id = serializers.SerializerMethodField()

    class Meta:
        model = Organisation
        fields = [
            'id',
            'name',
            'email',
            'phone',
            'organisation_type',
            'organisation_type_label',
            'city',
            'is_verified',
            'membership_status',
            'membership_id',
        ]

    def _membership(self, obj):
        request = self.context.get('request')
        if not request or not request.user or not request.user.is_authenticated:
            return None
        memberships = getattr(obj, 'current_user_memberships', None)
        if memberships is not None:
            return memberships[0] if memberships else None
        return OrganisationMembership.objects.filter(organisation=obj, player=request.user).first()

    def get_membership_status(self, obj):
        membership = self._membership(obj)
        return membership.status if membership else 'NONE'

    def get_membership_id(self, obj):
        membership = self._membership(obj)
        return membership.id if membership else None


class OrganisationMembershipSerializer(serializers.ModelSerializer):
    """Membership request data for organisers."""
    player_username = serializers.CharField(source='player.username', read_only=True)
    player_email = serializers.EmailField(source='player.email', read_only=True)
    organisation_name = serializers.CharField(source='organisation.name', read_only=True)

    class Meta:
        model = OrganisationMembership
        fields = [
            'id',
            'organisation',
            'organisation_name',
            'player',
            'player_username',
            'player_email',
            'status',
            'requested_at',
            'reviewed_at',
            'reviewed_by',
        ]
        read_only_fields = fields


class OrganisationRegistrationSerializer(serializers.Serializer):
    """Register an organisation and its owner user account."""
    organisation_name = serializers.CharField(max_length=255)
    contact_name = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    phone = serializers.CharField(max_length=32)
    organisation_type = serializers.ChoiceField(choices=Organisation.OrganisationType.choices)
    city = serializers.CharField(max_length=120)
    password = serializers.CharField(
        write_only=True,
        validators=[validate_password],
        style={'input_type': 'password'}
    )
    password_confirm = serializers.CharField(write_only=True, style={'input_type': 'password'})

    def validate_email(self, value):
        email = value.strip().lower()
        if CustomUser.objects.filter(email__iexact=email).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        if Organisation.objects.filter(email__iexact=email).exists():
            raise serializers.ValidationError("An organisation with this email already exists.")
        return email

    def validate_phone(self, value):
        phone = value.strip()
        if not phone:
            raise serializers.ValidationError("Phone number is required.")
        return phone

    def validate(self, attrs):
        if attrs['password'] != attrs['password_confirm']:
            raise serializers.ValidationError({
                'password_confirm': "Password fields didn't match."
            })
        return attrs

    def _unique_username(self, email, organisation_name):
        base = slugify(email.split('@')[0] or organisation_name) or 'organisation'
        username = base[:140]
        suffix = 1
        while CustomUser.objects.filter(username=username).exists():
            suffix_text = f"-{suffix}"
            username = f"{base[:150 - len(suffix_text)]}{suffix_text}"
            suffix += 1
        return username

    def create(self, validated_data):
        password = validated_data.pop('password')
        validated_data.pop('password_confirm')

        email = validated_data['email']
        with transaction.atomic():
            user = CustomUser.objects.create(
                username=self._unique_username(email, validated_data['organisation_name']),
                email=email,
                first_name=validated_data['contact_name'],
            )
            user.set_password(password)
            user.save()

            organisation = Organisation.objects.create(
                owner=user,
                name=validated_data['organisation_name'].strip(),
                contact_name=validated_data['contact_name'].strip(),
                email=email,
                phone=validated_data['phone'].strip(),
                organisation_type=validated_data['organisation_type'],
                city=validated_data['city'].strip(),
            )

        return organisation


class OrganisationLoginSerializer(serializers.Serializer):
    """Authenticate an organisation owner by organisation email and password."""
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, style={'input_type': 'password'})

    def validate(self, attrs):
        email = attrs['email'].strip().lower()
        password = attrs['password']
        user = authenticate(
            request=self.context.get('request'),
            username=email,
            password=password,
        )
        if user is None:
            raise serializers.ValidationError("Invalid organisation email or password.")
        if not user.is_active:
            raise serializers.ValidationError("This organisation account is disabled.")

        try:
            organisation = user.organisation
        except Organisation.DoesNotExist as exc:
            raise serializers.ValidationError("No organisation is attached to this account.") from exc

        attrs['user'] = user
        attrs['organisation'] = organisation
        return attrs


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


class TournamentSerializer(serializers.ModelSerializer):
    """Serializer for organisation tournament data."""
    organisation = OrganisationSerializer(read_only=True)
    game_label = serializers.CharField(source='get_game_display', read_only=True)
    status_label = serializers.CharField(source='get_status_display', read_only=True)
    registered_players_count = serializers.SerializerMethodField()
    eligibility = serializers.SerializerMethodField()

    class Meta:
        model = Tournament
        fields = [
            'id',
            'organisation',
            'name',
            'game',
            'game_label',
            'participation_amount',
            'max_players',
            'registered_players_count',
            'rules',
            'start_date',
            'status',
            'status_label',
            'eligibility',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'organisation',
            'game_label',
            'registered_players_count',
            'status',
            'status_label',
            'eligibility',
            'created_at',
            'updated_at',
        ]

    def get_eligibility(self, obj):
        return {
            'type': 'ORGANISATION_MEMBERS_ONLY',
            'organisation_id': obj.organisation_id,
            'description': f"Only players attached to {obj.organisation.name} can join.",
        }

    def get_registered_players_count(self, obj):
        return obj.registered_players_count


class PlayerTournamentSerializer(serializers.ModelSerializer):
    """Tournament data visible to approved organisation players.

    Includes per-player join state (is_registered / spots_left / is_full) so the
    frontend can render the correct Join / Leave action, mirroring open matches.
    """
    organisation = OrganisationDirectorySerializer(read_only=True)
    game_label = serializers.CharField(source='get_game_display', read_only=True)
    registered_players_count = serializers.SerializerMethodField()
    spots_left = serializers.SerializerMethodField()
    is_full = serializers.SerializerMethodField()
    is_registered = serializers.SerializerMethodField()

    class Meta:
        model = Tournament
        fields = [
            'id',
            'organisation',
            'name',
            'game',
            'game_label',
            'participation_amount',
            'max_players',
            'registered_players_count',
            'spots_left',
            'is_full',
            'is_registered',
            'rules',
            'start_date',
            'status',
        ]

    def get_registered_players_count(self, obj):
        return obj.registered_players_count

    def get_spots_left(self, obj):
        return max(obj.max_players - obj.registered_players_count, 0)

    def get_is_full(self, obj):
        return obj.is_full

    def get_is_registered(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        return TournamentRegistration.objects.filter(
            tournament=obj,
            player=request.user,
            status=TournamentRegistration.Status.REGISTERED,
        ).exists()


class TournamentRegistrationSerializer(serializers.ModelSerializer):
    """A participant row for an organiser's tournament."""
    player_id = serializers.IntegerField(source='player.id', read_only=True)
    player_username = serializers.CharField(source='player.username', read_only=True)
    player_email = serializers.EmailField(source='player.email', read_only=True)
    player_name = serializers.SerializerMethodField()

    class Meta:
        model = TournamentRegistration
        fields = [
            'id',
            'player_id',
            'player_username',
            'player_email',
            'player_name',
            'status',
            'amount_paid',
            'joined_at',
        ]

    def get_player_name(self, obj):
        profile = getattr(obj.player, 'profile', None)
        if profile:
            full = f"{profile.first_name} {profile.last_name}".strip()
            if full:
                return full
        return obj.player.username


class TournamentCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating an organisation tournament."""
    class Meta:
        model = Tournament
        fields = [
            'name',
            'game',
            'participation_amount',
            'max_players',
            'rules',
            'start_date',
        ]

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Tournament name is required.")
        return value

    def validate_rules(self, value):
        return value.strip()

    def validate_max_players(self, value):
        if value < 2:
            raise serializers.ValidationError("A tournament must allow at least 2 players.")
        return value

    def validate_participation_amount(self, value):
        if value < Decimal('0'):
            raise serializers.ValidationError("Participation amount cannot be negative.")
        return value

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
