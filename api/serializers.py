from rest_framework import serializers
from decimal import Decimal
from django.core.exceptions import ValidationError as DjangoValidationError
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth import authenticate, get_user_model
from django.utils.text import slugify
from django.db import IntegrityError, transaction
from accounts.models import CustomUser, Organisation, OrganisationMembership, Profile
from accounts.forms import signup_integrity_error_messages
from matches.models import (
    Match, MatchResult, Tournament, TournamentRegistration, TournamentPrize,
    TournamentStanding, TournamentPayout, TournamentMatch, TournamentMatchSubmission,
)
from wallet.models import Wallet, Transaction, Deposit, Withdrawal, OrganisationWallet, OrganisationTransaction
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


class PasswordResetConfirmSerializer(serializers.Serializer):
    """Validate an organiser password-reset link and set a new password.

    Resolves the user from the encoded uid, checks the one-time token
    (``default_token_generator``), and only accepts accounts that own an
    organisation.
    """
    uid = serializers.CharField(write_only=True)
    token = serializers.CharField(write_only=True)
    new_password = serializers.CharField(
        write_only=True,
        validators=[validate_password],
        style={'input_type': 'password'},
    )
    new_password_confirm = serializers.CharField(
        write_only=True,
        style={'input_type': 'password'},
    )

    def validate(self, attrs):
        from django.contrib.auth.tokens import default_token_generator
        from django.utils.http import urlsafe_base64_decode
        from django.utils.encoding import force_str

        if attrs['new_password'] != attrs['new_password_confirm']:
            raise serializers.ValidationError({
                'new_password_confirm': "Password fields didn't match.",
            })

        try:
            uid = force_str(urlsafe_base64_decode(attrs['uid']))
            user = CustomUser.objects.get(pk=uid)
        except (TypeError, ValueError, OverflowError, CustomUser.DoesNotExist):
            raise serializers.ValidationError({
                'token': 'This reset link is invalid or has expired.',
            })

        if not default_token_generator.check_token(user, attrs['token']):
            raise serializers.ValidationError({
                'token': 'This reset link is invalid or has expired.',
            })

        if not Organisation.objects.filter(owner=user).exists():
            raise serializers.ValidationError({
                'token': 'This reset link is not valid for an organisation account.',
            })

        attrs['user'] = user
        return attrs

    def save(self):
        user = self.validated_data['user']
        user.set_password(self.validated_data['new_password'])
        user.save(update_fields=['password'])
        return user


class WalletSerializer(serializers.ModelSerializer):
    """Serializer for wallet summary data"""
    class Meta:
        model = Wallet
        fields = ['id', 'balance']
        read_only_fields = ['id', 'balance']


class OrganisationWalletSerializer(serializers.ModelSerializer):
    """Serializer for organisation wallet summary data."""
    class Meta:
        model = OrganisationWallet
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


class OrganisationTransactionSerializer(serializers.ModelSerializer):
    """Serializer for organisation wallet transactions."""
    class Meta:
        model = OrganisationTransaction
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
        organisation = self.context.get('organisation')
        if organisation:
            wallet, _created = OrganisationWallet.objects.get_or_create(organisation=organisation)
            wallet_field = {'organisation_wallet': wallet}
        else:
            wallet, _created = Wallet.objects.get_or_create(user=user)
            wallet_field = {'wallet': wallet}
        ip_address = request.META.get('REMOTE_ADDR')
        user_agent = request.META.get('HTTP_USER_AGENT', '')[:500]

        validated_data.pop('mobile_number', None)
        deposit = Deposit(
            user=user,
            amount=validated_data['amount'],
            payment_method=validated_data['payment_method'],
            status='PENDING',
            **wallet_field,
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
        organisation = self.context.get('organisation')

        with transaction.atomic():
            if organisation:
                wallet, _created = OrganisationWallet.objects.get_or_create(organisation=organisation)
            else:
                wallet, _created = Wallet.objects.get_or_create(user=user)
            wallet = wallet.__class__.objects.select_for_update().get(pk=wallet.pk)

            withdrawal = Withdrawal(
                user=user,
                amount=validated_data['amount'],
                payment_method=validated_data['payment_method'],
                account_details=validated_data['account_details'],
                status='PENDING',
                **({'organisation_wallet': wallet} if organisation else {'wallet': wallet}),
                ip_address=ip_address,
                user_agent=user_agent,
            )
            try:
                withdrawal.full_clean()
            except DjangoValidationError as exc:
                # Surface model validation (amount limits, balance, account
                # details, daily limits) as a clean 400 instead of a 500.
                raise serializers.ValidationError(
                    exc.message_dict if hasattr(exc, 'message_dict') else exc.messages
                )

            if wallet.balance < withdrawal.amount:
                raise serializers.ValidationError({
                    'amount': f'Insufficient balance. Your balance is ZMW {wallet.balance:.2f}'
                })

            withdrawal.save()
            wallet.balance -= withdrawal.amount
            wallet.save(update_fields=['balance'])
            transaction_model = OrganisationTransaction if organisation else Transaction
            transaction_model.objects.create(
                wallet=wallet,
                amount=-withdrawal.amount,
                transaction_type='WITHDRAWAL',
                description=f'Withdrawal request - {withdrawal.get_payment_method_display()}',
            )
        return withdrawal


class WithdrawalSerializer(serializers.ModelSerializer):
    """Read serializer for a user's withdrawal request (status + reference)."""
    status_label = serializers.CharField(source='get_status_display', read_only=True)
    payment_method_label = serializers.CharField(source='get_payment_method_display', read_only=True)
    reference = serializers.SerializerMethodField()
    account_details_masked = serializers.SerializerMethodField()

    class Meta:
        model = Withdrawal
        fields = [
            'id',
            'amount',
            'status',
            'status_label',
            'payment_method',
            'payment_method_label',
            'account_details_masked',
            'reference',
            'failure_reason',
            'retry_count',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields

    def get_reference(self, obj):
        return obj.transaction_id or obj.gateway_transaction_id or None

    def get_account_details_masked(self, obj):
        raw = (obj.account_details or '').strip()
        if not raw:
            return ''
        # Show only the last 4 characters of the payout destination.
        tail = raw[-4:]
        return f"•••• {tail}" if len(raw) > 4 else raw


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


class TournamentPrizeSerializer(serializers.ModelSerializer):
    """A configured prize position with its live cash value."""
    expected_amount = serializers.SerializerMethodField()

    class Meta:
        model = TournamentPrize
        fields = ['position', 'percentage', 'expected_amount']

    def get_expected_amount(self, obj):
        pool = self.context.get('prize_pool')
        return str(obj.expected_amount(pool))


class TournamentFinancialsMixin:
    """Shared serializer helpers for the entry-fee split and prize pool."""

    def get_fee_percent(self, obj):
        return str(obj.fee_percent())

    def get_platform_fee_percent(self, obj):
        return str(obj.platform_fee_percent)

    def get_fee_settlement_status(self, obj):
        settlement = getattr(obj, 'fee_settlement', None)
        return settlement.status if settlement else 'AWAITING_FULL_CAPACITY'

    def get_entry_breakdown(self, obj):
        settlement = getattr(obj, 'fee_settlement', None)
        is_settled = bool(
            settlement
            and settlement.status in ('RESERVED', 'RECOGNIZED')
        )
        if is_settled:
            fee, contribution = obj.split_entry(obj.participation_amount)
        else:
            fee = Decimal('0.00')
            contribution = Decimal(obj.participation_amount)
        return {
            'entry_fee': str(obj.participation_amount),
            'platform_fee': str(fee),
            'prize_contribution': str(contribution),
            'fee_status': self.get_fee_settlement_status(obj),
        }

    def get_prize_pool(self, obj):
        return str(obj.prize_pool)

    def get_prizes(self, obj):
        pool = obj.prize_pool
        return TournamentPrizeSerializer(
            obj.prizes.all(), many=True, context={'prize_pool': pool},
        ).data


class TournamentSerializer(TournamentFinancialsMixin, serializers.ModelSerializer):
    """Serializer for organisation tournament data."""
    organisation = OrganisationSerializer(read_only=True)
    game_label = serializers.CharField(source='get_game_display', read_only=True)
    status_label = serializers.CharField(source='get_status_display', read_only=True)
    registered_players_count = serializers.SerializerMethodField()
    eligibility = serializers.SerializerMethodField()
    display_status = serializers.CharField(read_only=True)
    display_status_label = serializers.SerializerMethodField()
    platform_fee_percent = serializers.SerializerMethodField()
    fee_percent = serializers.SerializerMethodField()
    fee_settlement_status = serializers.SerializerMethodField()
    entry_breakdown = serializers.SerializerMethodField()
    prize_pool = serializers.SerializerMethodField()
    platform_fee_total = serializers.SerializerMethodField()
    gross_entries = serializers.SerializerMethodField()
    prizes = serializers.SerializerMethodField()

    class Meta:
        model = Tournament
        fields = [
            'id',
            'organisation',
            'name',
            'game',
            'game_label',
            'format',
            'platform_fee_percent',
            'home_and_away',
            'participation_amount',
            'max_players',
            'registered_players_count',
            'rules',
            'start_date',
            'registration_opens_at',
            'registration_closes_at',
            'status',
            'status_label',
            'display_status',
            'display_status_label',
            'fee_settlement_status',
            'eligibility',
            'fee_percent',
            'entry_breakdown',
            'prize_pool',
            'platform_fee_total',
            'gross_entries',
            'prizes',
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
            'display_status',
            'display_status_label',
            'eligibility',
            'fee_percent',
            'entry_breakdown',
            'prize_pool',
            'platform_fee_total',
            'gross_entries',
            'prizes',
            'created_at',
            'updated_at',
        ]

    def get_display_status_label(self, obj):
        return dict(Tournament.STATUS_CHOICES).get(obj.display_status, obj.display_status)

    def get_platform_fee_total(self, obj):
        return str(obj.platform_fee_total)

    def get_gross_entries(self, obj):
        return str(obj.gross_entries)

    def get_eligibility(self, obj):
        return {
            'type': 'ORGANISATION_MEMBERS_ONLY',
            'organisation_id': obj.organisation_id,
            'description': f"Only players attached to {obj.organisation.name} can join.",
        }

    def get_registered_players_count(self, obj):
        return obj.registered_players_count


class PlayerTournamentSerializer(TournamentFinancialsMixin, serializers.ModelSerializer):
    """Tournament data visible to approved organisation players.

    Includes per-player join state (is_registered / spots_left / is_full) so the
    frontend can render the correct Join / Leave action, mirroring open matches.
    Also exposes the entry-fee split, live prize pool and configured prizes so
    players see the financial structure before registering.
    """
    organisation = OrganisationDirectorySerializer(read_only=True)
    game_label = serializers.CharField(source='get_game_display', read_only=True)
    registered_players_count = serializers.SerializerMethodField()
    spots_left = serializers.SerializerMethodField()
    is_full = serializers.SerializerMethodField()
    is_registered = serializers.SerializerMethodField()
    fee_percent = serializers.SerializerMethodField()
    entry_breakdown = serializers.SerializerMethodField()
    prize_pool = serializers.SerializerMethodField()
    prizes = serializers.SerializerMethodField()
    my_position = serializers.SerializerMethodField()
    my_points = serializers.SerializerMethodField()
    my_winnings = serializers.SerializerMethodField()
    display_status = serializers.CharField(read_only=True)
    display_status_label = serializers.SerializerMethodField()
    is_registration_open = serializers.BooleanField(read_only=True)
    fee_settlement_status = serializers.SerializerMethodField()

    class Meta:
        model = Tournament
        fields = [
            'id',
            'organisation',
            'name',
            'game',
            'game_label',
            'format',
            'home_and_away',
            'participation_amount',
            'max_players',
            'registered_players_count',
            'spots_left',
            'is_full',
            'is_registered',
            'fee_percent',
            'entry_breakdown',
            'prize_pool',
            'prizes',
            'my_position',
            'my_points',
            'my_winnings',
            'rules',
            'start_date',
            'registration_closes_at',
            'status',
            'display_status',
            'display_status_label',
            'is_registration_open',
            'fee_settlement_status',
        ]

    def get_display_status_label(self, obj):
        return dict(Tournament.STATUS_CHOICES).get(obj.display_status, obj.display_status)

    def _my_standing(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None
        return obj.standings.filter(player=request.user).first()

    def get_my_position(self, obj):
        standing = self._my_standing(obj)
        return standing.position if standing else None

    def get_my_points(self, obj):
        standing = self._my_standing(obj)
        return str(standing.points) if standing and standing.points is not None else None

    def get_my_winnings(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None
        payout = obj.payouts.filter(player=request.user).first()
        if not payout:
            return None
        return {'amount': str(payout.amount), 'status': payout.status}

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
    player_label = serializers.SerializerMethodField()

    class Meta:
        model = TournamentRegistration
        fields = [
            'id',
            'player_id',
            'player_username',
            'player_email',
            'player_name',
            'player_label',
            'team_name',
            'phone',
            'status',
            'amount_paid',
            'platform_fee',
            'prize_contribution',
            'joined_at',
        ]

    def get_player_name(self, obj):
        profile = getattr(obj.player, 'profile', None)
        if profile:
            full = f"{profile.first_name} {profile.last_name}".strip()
            if full:
                return full
        return obj.player.username

    def get_player_label(self, obj):
        """'Username (Team Name)' — as league fixtures/standings should show."""
        if obj.team_name:
            return f"{obj.player.username} ({obj.team_name})"
        return obj.player.username


class TournamentPrizeInputSerializer(serializers.Serializer):
    """A single prize position submitted when creating/configuring a tournament."""
    position = serializers.IntegerField(min_value=1)
    percentage = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=Decimal('0'))


class TournamentCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating an organisation tournament."""
    prizes = TournamentPrizeInputSerializer(many=True, required=False)
    platform_fee_percent = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        required=False,
        default=Tournament.default_fee_percent(),
    )

    class Meta:
        model = Tournament
        fields = [
            'name',
            'game',
            'format',
            'platform_fee_percent',
            'home_and_away',
            'participation_amount',
            'max_players',
            'rules',
            'start_date',
            'registration_opens_at',
            'registration_closes_at',
            'prizes',
        ]
        extra_kwargs = {
            'platform_fee_percent': {'required': False},
            'home_and_away': {'required': False},
        }

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

    def validate_platform_fee_percent(self, value):
        if not value.is_finite() or value < Decimal('0') or value > Decimal('10'):
            raise serializers.ValidationError(
                "PlayArena administration fee must be between 0 and 10 percent."
            )
        return value

    def validate_prizes(self, value):
        if not value:
            return value
        positions = [p['position'] for p in value]
        if len(positions) != len(set(positions)):
            raise serializers.ValidationError("Prize positions must be unique.")
        total = sum((p['percentage'] for p in value), Decimal('0'))
        if total > Decimal('100'):
            raise serializers.ValidationError(
                f"Total prize distribution is {total}%, which exceeds 100% of the pool."
            )
        return value

    def create(self, validated_data):
        prizes = validated_data.pop('prizes', [])
        tournament = super().create(validated_data)
        for prize in prizes:
            TournamentPrize.objects.create(
                tournament=tournament,
                position=prize['position'],
                percentage=prize['percentage'],
            )
        return tournament

def _player_display_name(player):
    profile = getattr(player, 'profile', None)
    if profile:
        full = f"{profile.first_name} {profile.last_name}".strip()
        if full:
            return full
    return player.username


def tournament_team_map(tournament):
    """Map of {player_id: team_name} for a tournament's active registrations."""
    if tournament is None:
        return {}
    from matches.models import TournamentRegistration
    return {
        r.player_id: r.team_name
        for r in tournament.registrations.filter(
            status=TournamentRegistration.Status.REGISTERED,
        ).only('player_id', 'team_name')
        if r.team_name
    }


def _player_label(player, team_map=None):
    """Display a player as 'Username (Team Name)' when a team is known."""
    base = _player_display_name(player)
    if team_map:
        team = team_map.get(player.id)
        if team:
            return f"{base} ({team})"
    return base


class _TeamMapMixin:
    """Lazily builds & caches a per-tournament {player_id: team_name} map."""

    def _team_map_for(self, tournament):
        if tournament is None:
            return {}
        cache = self.context.setdefault('_team_maps', {})
        if tournament.id not in cache:
            cache[tournament.id] = tournament_team_map(tournament)
        return cache[tournament.id]


class TournamentStandingSerializer(_TeamMapMixin, serializers.ModelSerializer):
    """A player's ranked position in a tournament."""
    player_id = serializers.IntegerField(source='player.id', read_only=True)
    player_username = serializers.CharField(source='player.username', read_only=True)
    player_name = serializers.SerializerMethodField()
    team_name = serializers.SerializerMethodField()

    class Meta:
        model = TournamentStanding
        fields = ['position', 'player_id', 'player_username', 'player_name', 'team_name', 'points']

    def get_player_name(self, obj):
        return _player_label(obj.player, self._team_map_for(getattr(obj, 'tournament', None)))

    def get_team_name(self, obj):
        return self._team_map_for(getattr(obj, 'tournament', None)).get(obj.player_id) or None


class TournamentStandingInputSerializer(serializers.Serializer):
    """A single standing row submitted by an organiser."""
    player_id = serializers.IntegerField()
    position = serializers.IntegerField(min_value=1)
    points = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False, allow_null=True,
    )


class TournamentPayoutSerializer(_TeamMapMixin, serializers.ModelSerializer):
    """An automatic payout record for a winning position."""
    player_id = serializers.IntegerField(source='player.id', read_only=True)
    player_username = serializers.CharField(source='player.username', read_only=True)
    player_name = serializers.SerializerMethodField()
    team_name = serializers.SerializerMethodField()
    percentage = serializers.SerializerMethodField()
    transaction_id = serializers.IntegerField(source='transaction.id', read_only=True, allow_null=True)

    class Meta:
        model = TournamentPayout
        fields = [
            'id',
            'position',
            'percentage',
            'player_id',
            'player_username',
            'player_name',
            'team_name',
            'amount',
            'status',
            'transaction_id',
            'failure_reason',
            'created_at',
            'paid_at',
        ]

    def get_player_name(self, obj):
        return _player_label(obj.player, self._team_map_for(getattr(obj, 'tournament', None)))

    def get_team_name(self, obj):
        return self._team_map_for(getattr(obj, 'tournament', None)).get(obj.player_id) or None

    def get_percentage(self, obj):
        """The configured prize percentage for this position (for the record)."""
        cache = self.context.setdefault('_prize_pcts', {})
        tid = obj.tournament_id
        if tid not in cache:
            from matches.models import TournamentPrize
            cache[tid] = {
                p.position: p.percentage
                for p in TournamentPrize.objects.filter(tournament_id=tid)
            }
        pct = cache[tid].get(obj.position)
        return str(pct) if pct is not None else None


def _player_brief(player, team_map=None):
    if not player:
        return None
    return {
        'id': player.id,
        'name': _player_label(player, team_map),
        'team_name': (team_map.get(player.id) if team_map else None) or None,
    }


class TournamentMatchSubmissionSerializer(serializers.ModelSerializer):
    """One player's submitted result, shown to the organiser for dispute review."""
    player = serializers.SerializerMethodField()
    winner = serializers.SerializerMethodField()
    evidence_url = serializers.SerializerMethodField()

    class Meta:
        model = TournamentMatchSubmission
        fields = ['player', 'winner', 'player1_score', 'player2_score', 'evidence_url', 'submitted_at']

    def get_player(self, obj):
        return _player_brief(obj.player, self.context.get('_active_team_map'))

    def get_winner(self, obj):
        return _player_brief(obj.winner, self.context.get('_active_team_map'))

    def get_evidence_url(self, obj):
        if not obj.evidence:
            return None
        request = self.context.get('request')
        url = obj.evidence.url
        return request.build_absolute_uri(url) if request else url


class TournamentMatchSerializer(_TeamMapMixin, serializers.ModelSerializer):
    """A bracket match with lightweight player info for rendering the bracket."""
    player1 = serializers.SerializerMethodField()
    player2 = serializers.SerializerMethodField()
    winner = serializers.SerializerMethodField()
    reported_winner = serializers.SerializerMethodField()
    submissions = serializers.SerializerMethodField()

    class Meta:
        model = TournamentMatch
        fields = [
            'id',
            'round_number',
            'slot_number',
            'player1',
            'player2',
            'player1_score',
            'player2_score',
            'winner',
            'reported_winner',
            'submissions',
            'status',
            'next_match',
            'next_slot',
        ]

    def get_submissions(self, obj):
        subs = obj.submissions.all() if hasattr(obj, 'submissions') else []
        ctx = dict(self.context)
        ctx['_active_team_map'] = self._team_map_for(getattr(obj, 'tournament', None))
        return TournamentMatchSubmissionSerializer(subs, many=True, context=ctx).data

    def get_player1(self, obj):
        return _player_brief(obj.player1, self._team_map_for(getattr(obj, 'tournament', None)))

    def get_player2(self, obj):
        return _player_brief(obj.player2, self._team_map_for(getattr(obj, 'tournament', None)))

    def get_winner(self, obj):
        return _player_brief(obj.winner, self._team_map_for(getattr(obj, 'tournament', None)))

    def get_reported_winner(self, obj):
        return _player_brief(obj.reported_winner, self._team_map_for(getattr(obj, 'tournament', None)))


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
