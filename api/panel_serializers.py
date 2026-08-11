"""Serializers for the admin/support panel API (read + light action payloads)."""
from rest_framework import serializers
from django.contrib.auth import get_user_model

from matches.models import Match, Evidence, Tournament
from wallet.models import Wallet, Transaction, Deposit, Withdrawal
from panel.models import Dispute
from accounts.models import Organisation

User = get_user_model()


class PanelUserSerializer(serializers.ModelSerializer):
    wallet_balance = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'date_joined', 'is_active',
            'is_support_staff', 'is_staff', 'is_superuser', 'wallet_balance',
        ]

    def get_wallet_balance(self, obj):
        wallet = getattr(obj, 'wallet', None)
        return str(wallet.balance) if wallet else '0.00'


class PanelMatchSerializer(serializers.ModelSerializer):
    creator_username = serializers.CharField(source='creator.username', read_only=True)
    joiner_username = serializers.CharField(source='joiner.username', read_only=True, allow_null=True)
    winner_username = serializers.CharField(source='winner.username', read_only=True, allow_null=True)
    game_display = serializers.CharField(source='get_game_display', read_only=True)
    device_display = serializers.CharField(source='get_device_display', read_only=True)

    class Meta:
        model = Match
        fields = [
            'id', 'game', 'game_display', 'device', 'device_display', 'privacy',
            'joining_code', 'amount', 'winnings', 'status', 'created_at',
            'creator', 'creator_username', 'joiner', 'joiner_username',
            'winner', 'winner_username',
        ]


class EvidenceSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)
    verified_by_username = serializers.CharField(source='verified_by.username', read_only=True, allow_null=True)
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = Evidence
        fields = [
            'id', 'user', 'username', 'file_url', 'file_type', 'uploaded_at',
            'description', 'is_verified', 'verified_by_username', 'verified_at',
        ]

    def get_file_url(self, obj):
        request = self.context.get('request')
        try:
            url = obj.file.url
        except Exception:
            return None
        return request.build_absolute_uri(url) if request else url


class PanelWalletSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)
    email = serializers.CharField(source='user.email', read_only=True)
    user_id = serializers.IntegerField(source='user.id', read_only=True)

    class Meta:
        model = Wallet
        fields = ['id', 'user_id', 'username', 'email', 'balance']


class PanelTransactionSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='wallet.user.username', read_only=True)
    type_display = serializers.CharField(source='get_transaction_type_display', read_only=True)

    class Meta:
        model = Transaction
        fields = ['id', 'username', 'amount', 'transaction_type', 'type_display', 'description', 'created_at']


class PanelDepositSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)
    method_display = serializers.CharField(source='get_payment_method_display', read_only=True)

    class Meta:
        model = Deposit
        fields = [
            'id', 'username', 'amount', 'status', 'payment_method', 'method_display',
            'transaction_id', 'created_at', 'updated_at', 'completed_at',
        ]


class PanelWithdrawalSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)
    method_display = serializers.CharField(source='get_payment_method_display', read_only=True)

    class Meta:
        model = Withdrawal
        fields = [
            'id', 'username', 'amount', 'status', 'payment_method', 'method_display',
            'account_details', 'created_at', 'updated_at',
        ]


class PanelDisputeSerializer(serializers.ModelSerializer):
    match_id = serializers.IntegerField(source='match.id', read_only=True)
    match_game = serializers.CharField(source='match.get_game_display', read_only=True)
    match_amount = serializers.DecimalField(source='match.amount', max_digits=10, decimal_places=2, read_only=True)
    match_status = serializers.CharField(source='match.status', read_only=True)
    creator_username = serializers.CharField(source='match.creator.username', read_only=True)
    joiner_username = serializers.CharField(source='match.joiner.username', read_only=True, allow_null=True)
    assigned_to_username = serializers.CharField(source='assigned_to.username', read_only=True, allow_null=True)
    escalated_by_username = serializers.CharField(source='escalated_by.username', read_only=True, allow_null=True)

    class Meta:
        model = Dispute
        fields = [
            'id', 'match_id', 'match_game', 'match_amount', 'match_status', 'status',
            'created_at', 'assigned_to', 'assigned_to_username', 'resolution_notes',
            'resolved_at', 'escalated_at', 'escalated_by_username', 'escalation_reason',
            'creator_username', 'joiner_username',
        ]


class PanelDisputeDetailSerializer(PanelDisputeSerializer):
    """Dispute detail including the match, participants and evidence."""
    match = PanelMatchSerializer(read_only=True)
    evidence = serializers.SerializerMethodField()
    participants = serializers.SerializerMethodField()

    class Meta(PanelDisputeSerializer.Meta):
        fields = PanelDisputeSerializer.Meta.fields + ['match', 'evidence', 'participants']

    def get_evidence(self, obj):
        qs = Evidence.objects.filter(match=obj.match).select_related('user', 'verified_by').order_by('-uploaded_at')
        return EvidenceSerializer(qs, many=True, context=self.context).data

    def get_participants(self, obj):
        parts = [obj.match.creator]
        if obj.match.joiner:
            parts.append(obj.match.joiner)
        return [{'id': u.id, 'username': u.username, 'is_active': u.is_active} for u in parts]


# ---------------------------------------------------------------- Organisers
class PanelOrganisationSerializer(serializers.ModelSerializer):
    """Organiser row for the admin directory. Availability is derived from
    verification + owner account status (organisers have no dedicated flag)."""
    type_label = serializers.CharField(source='get_organisation_type_display', read_only=True)
    owner_id = serializers.IntegerField(source='owner.id', read_only=True)
    owner_username = serializers.CharField(source='owner.username', read_only=True)
    owner_active = serializers.BooleanField(source='owner.is_active', read_only=True)
    tournaments_count = serializers.SerializerMethodField()
    active_tournaments_count = serializers.SerializerMethodField()
    members_count = serializers.SerializerMethodField()
    is_available = serializers.SerializerMethodField()

    class Meta:
        model = Organisation
        fields = [
            'id', 'name', 'contact_name', 'email', 'phone',
            'organisation_type', 'type_label', 'city', 'is_verified',
            'created_at', 'owner_id', 'owner_username', 'owner_active',
            'tournaments_count', 'active_tournaments_count', 'members_count',
            'is_available',
        ]

    def get_tournaments_count(self, obj):
        return getattr(obj, 'tournaments_count', None) if hasattr(obj, 'tournaments_count') else obj.tournaments.count()

    def get_active_tournaments_count(self, obj):
        val = getattr(obj, 'active_tournaments_count', None)
        if val is not None:
            return val
        return obj.tournaments.filter(status__in=['OPEN', 'IN_PROGRESS']).count()

    def get_members_count(self, obj):
        val = getattr(obj, 'members_count', None)
        if val is not None:
            return val
        return obj.memberships.filter(status='APPROVED').count()

    def get_is_available(self, obj):
        return bool(obj.is_verified and obj.owner.is_active)


class PanelTournamentSerializer(serializers.ModelSerializer):
    game_label = serializers.CharField(source='get_game_display', read_only=True)
    status_label = serializers.CharField(source='get_status_display', read_only=True)
    registered_players_count = serializers.SerializerMethodField()

    class Meta:
        model = Tournament
        fields = [
            'id', 'name', 'game', 'game_label', 'participation_amount',
            'max_players', 'registered_players_count', 'status', 'status_label',
            'start_date', 'created_at',
        ]

    def get_registered_players_count(self, obj):
        # Registration model not yet implemented; mirrors api.serializers.TournamentSerializer.
        return 0


class PanelOrganisationDetailSerializer(PanelOrganisationSerializer):
    tournaments = serializers.SerializerMethodField()

    class Meta(PanelOrganisationSerializer.Meta):
        fields = PanelOrganisationSerializer.Meta.fields + ['tournaments']

    def get_tournaments(self, obj):
        qs = obj.tournaments.all().order_by('-created_at')
        return PanelTournamentSerializer(qs, many=True, context=self.context).data
