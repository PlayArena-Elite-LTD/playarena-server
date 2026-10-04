"""Admin/support panel API endpoints. Mirrors the Django panel app over REST.

All endpoints require support-staff or Django admin access and are additive:
they reuse the existing wallet/dispute business logic and never change schema.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q, Count, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from datetime import timedelta

from rest_framework import permissions, status
from rest_framework.generics import ListAPIView
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from matches.models import Match, Evidence, Tournament
from wallet.models import Wallet, Transaction, Deposit, Withdrawal
from panel.models import Dispute
from alert.models import Notification
from accounts.models import Organisation

from .panel_serializers import (
    PanelUserSerializer, PanelMatchSerializer, EvidenceSerializer,
    PanelWalletSerializer, PanelTransactionSerializer, PanelDepositSerializer,
    PanelWithdrawalSerializer, PanelDisputeSerializer, PanelDisputeDetailSerializer,
    PanelOrganisationSerializer, PanelOrganisationDetailSerializer,
)

User = get_user_model()


class IsSupportStaff(permissions.BasePermission):
    """Allow support staff, Django staff, or superusers (mirrors support_staff_required)."""
    message = "Support staff access required."

    def has_permission(self, request, view):
        u = request.user
        return bool(
            u and u.is_authenticated and
            (getattr(u, 'is_support_staff', False) or u.is_staff or u.is_superuser)
        )


class PanelPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = 'page_size'
    max_page_size = 100


class LargePanelPagination(PanelPagination):
    page_size = 50


# ---------------------------------------------------------------- Dashboard
class PanelStatsView(APIView):
    permission_classes = [IsSupportStaff]

    def get(self, request):
        week_start = timezone.now() - timedelta(days=7)
        data = {
            'total_users': User.objects.count(),
            'active_users': User.objects.filter(is_active=True).count(),
            'recent_users': User.objects.filter(date_joined__gte=week_start).count(),
            'total_matches': Match.objects.count(),
            'open_matches': Match.objects.filter(status='OPEN').count(),
            'disputed_matches': Match.objects.filter(status='DISPUTED').count(),
            'total_wallet_balance': str(Wallet.objects.aggregate(t=Sum('balance'))['t'] or Decimal('0.00')),
            'pending_deposits': Deposit.objects.filter(status__in=['PENDING', 'PROCESSING']).count(),
            'pending_withdrawals': Withdrawal.objects.filter(status__in=['PENDING', 'PROCESSING']).count(),
            'open_disputes': Dispute.objects.filter(status='OPEN').count(),
            'escalated_disputes': Dispute.objects.filter(status='ESCALATED').count(),
        }
        return Response(data)


# ---------------------------------------------------------------- Users
class PanelUserListView(ListAPIView):
    permission_classes = [IsSupportStaff]
    serializer_class = PanelUserSerializer
    pagination_class = PanelPagination

    def get_queryset(self):
        qs = User.objects.select_related('wallet').all().order_by('-date_joined')
        q = self.request.query_params.get('q', '').strip()
        status_f = self.request.query_params.get('status', '')
        role = self.request.query_params.get('role', '')
        if q:
            qs = qs.filter(Q(username__icontains=q) | Q(email__icontains=q))
        if status_f == 'active':
            qs = qs.filter(is_active=True)
        elif status_f == 'disabled':
            qs = qs.filter(is_active=False)
        if role == 'support_staff':
            qs = qs.filter(is_support_staff=True)
        elif role == 'staff':
            qs = qs.filter(is_staff=True)
        return qs


class PanelUserToggleView(APIView):
    permission_classes = [IsSupportStaff]

    def post(self, request, user_id):
        user = get_object_or_404(User, id=user_id)
        action = request.data.get('action', 'disable')
        if action == 'disable':
            if user.is_superuser:
                return Response({'detail': 'Cannot disable a superuser account.'}, status=400)
            if user.id == request.user.id:
                return Response({'detail': 'You cannot disable your own account.'}, status=400)
            user.is_active = False
            user.save(update_fields=['is_active'])
            return Response({'message': f'{user.username} disabled.', 'is_active': False})
        else:
            user.is_active = True
            user.save(update_fields=['is_active'])
            return Response({'message': f'{user.username} enabled.', 'is_active': True})


# ---------------------------------------------------------------- Matches
class PanelMatchListView(ListAPIView):
    permission_classes = [IsSupportStaff]
    serializer_class = PanelMatchSerializer
    pagination_class = PanelPagination

    def get_queryset(self):
        qs = Match.objects.select_related('creator', 'joiner', 'winner').order_by('-created_at')
        status_f = self.request.query_params.get('status', '')
        game = self.request.query_params.get('game', '')
        q = self.request.query_params.get('q', '').strip()
        if status_f:
            qs = qs.filter(status=status_f)
        if game:
            qs = qs.filter(game=game)
        if q:
            qs = qs.filter(
                Q(joining_code__icontains=q) |
                Q(creator__username__icontains=q) |
                Q(joiner__username__icontains=q)
            )
        return qs


class PanelMatchDetailView(APIView):
    permission_classes = [IsSupportStaff]

    def get(self, request, match_id):
        match = get_object_or_404(Match.objects.select_related('creator', 'joiner', 'winner'), id=match_id)
        evidence = Evidence.objects.filter(match=match).select_related('user', 'verified_by').order_by('-uploaded_at')
        return Response({
            'match': PanelMatchSerializer(match).data,
            'evidence': EvidenceSerializer(evidence, many=True, context={'request': request}).data,
        })


class PanelVerifyEvidenceView(APIView):
    permission_classes = [IsSupportStaff]

    def post(self, request, evidence_id):
        evidence = get_object_or_404(Evidence, id=evidence_id)
        if 'description' in request.data:
            evidence.description = request.data.get('description') or evidence.description
        if request.data.get('is_verified'):
            evidence.is_verified = True
            evidence.verified_by = request.user
            evidence.verified_at = timezone.now()
        evidence.save()
        return Response(EvidenceSerializer(evidence, context={'request': request}).data)


# ---------------------------------------------------------------- Wallets
class PanelWalletListView(ListAPIView):
    permission_classes = [IsSupportStaff]
    serializer_class = PanelWalletSerializer
    pagination_class = PanelPagination

    def get_queryset(self):
        qs = Wallet.objects.select_related('user').order_by('user__username')
        q = self.request.query_params.get('q', '').strip()
        if q:
            qs = qs.filter(Q(user__username__icontains=q) | Q(user__email__icontains=q))
        return qs


class PanelWalletReconcileView(APIView):
    permission_classes = [IsSupportStaff]

    def post(self, request, wallet_id):
        wallet = get_object_or_404(Wallet, id=wallet_id)
        result = wallet.verify_balance_integrity()
        if result['is_valid']:
            return Response({'message': 'Wallet already balanced.', 'balance': str(wallet.balance)})
        wallet.recalculate_balance()
        return Response({
            'message': 'Wallet reconciled.',
            'old_balance': str(result['actual_balance']),
            'new_balance': str(result['expected_balance']),
        })


class PanelTransactionListView(ListAPIView):
    permission_classes = [IsSupportStaff]
    serializer_class = PanelTransactionSerializer
    pagination_class = LargePanelPagination

    def get_queryset(self):
        qs = Transaction.objects.select_related('wallet__user').order_by('-created_at')
        q = self.request.query_params.get('q', '').strip()
        txn_type = self.request.query_params.get('type', '')
        if q:
            qs = qs.filter(wallet__user__username__icontains=q)
        if txn_type:
            qs = qs.filter(transaction_type=txn_type)
        return qs


# ---------------------------------------------------------------- Deposits
class PanelDepositListView(ListAPIView):
    permission_classes = [IsSupportStaff]
    serializer_class = PanelDepositSerializer
    pagination_class = PanelPagination

    def get_queryset(self):
        qs = Deposit.objects.select_related('user').order_by('-created_at')
        status_f = self.request.query_params.get('status', '')
        q = self.request.query_params.get('q', '').strip()
        if status_f:
            qs = qs.filter(status=status_f)
        if q:
            qs = qs.filter(user__username__icontains=q)
        return qs


class PanelDepositCompleteView(APIView):
    permission_classes = [IsSupportStaff]

    @transaction.atomic
    def post(self, request, deposit_id):
        deposit = get_object_or_404(Deposit, id=deposit_id)
        if deposit.status == 'COMPLETED':
            return Response({'detail': 'Deposit is already completed.'}, status=400)
        if deposit.status in ['FAILED', 'CANCELLED']:
            return Response({'detail': 'Cannot complete a failed or cancelled deposit.'}, status=400)
        wallet = deposit.wallet
        if wallet is None:
            wallet, _ = Wallet.objects.get_or_create(user=deposit.user)
        wallet.balance += deposit.amount
        wallet.save(update_fields=['balance'])
        Transaction.objects.create(
            wallet=wallet,
            amount=deposit.amount,
            transaction_type='DEPOSIT',
            description=f"Deposit of ZMW {deposit.amount} via {deposit.get_payment_method_display()}",
        )
        Deposit.objects.filter(id=deposit.id).update(status='COMPLETED', updated_at=timezone.now())
        deposit.refresh_from_db()
        return Response(PanelDepositSerializer(deposit).data)


# ---------------------------------------------------------------- Withdrawals
class PanelWithdrawalListView(ListAPIView):
    permission_classes = [IsSupportStaff]
    serializer_class = PanelWithdrawalSerializer
    pagination_class = PanelPagination

    def get_queryset(self):
        qs = Withdrawal.objects.select_related('user').order_by('-created_at')
        status_f = self.request.query_params.get('status', '')
        q = self.request.query_params.get('q', '').strip()
        if status_f:
            qs = qs.filter(status=status_f)
        if q:
            qs = qs.filter(user__username__icontains=q)
        return qs


class PanelWithdrawalActionView(APIView):
    permission_classes = [IsSupportStaff]

    @transaction.atomic
    def post(self, request, withdrawal_id):
        from wallet.utils import process_withdrawal_and_debit_wallet, refund_withdrawal_reservation
        withdrawal = get_object_or_404(Withdrawal, id=withdrawal_id)
        action = request.data.get('action')  # complete | fail | cancel

        if action == 'complete':
            if withdrawal.status == 'COMPLETED':
                return Response({'detail': 'Withdrawal is already completed.'}, status=400)
            if withdrawal.status in ['FAILED', 'CANCELLED']:
                return Response({'detail': 'Cannot complete a failed or cancelled withdrawal.'}, status=400)
            completion = process_withdrawal_and_debit_wallet(withdrawal)
            if not completion.get('success'):
                return Response({'detail': completion.get('message', 'Could not complete withdrawal.')}, status=400)
            withdrawal.refresh_from_db()
        elif action in ('fail', 'cancel'):
            if withdrawal.status not in ['PENDING', 'PROCESSING']:
                return Response({'detail': 'Only pending/processing withdrawals can be updated.'}, status=400)
            new_status = 'FAILED' if action == 'fail' else 'CANCELLED'
            Withdrawal.objects.filter(id=withdrawal.id).update(status=new_status, updated_at=timezone.now())
            refund_withdrawal_reservation(withdrawal, f'Withdrawal {new_status.lower()} by admin (panel API)')
            withdrawal.refresh_from_db()
        else:
            return Response({'detail': 'Invalid action. Use complete, fail, or cancel.'}, status=400)

        return Response(PanelWithdrawalSerializer(withdrawal).data)


# ---------------------------------------------------------------- Disputes
class PanelDisputeListView(ListAPIView):
    permission_classes = [IsSupportStaff]
    serializer_class = PanelDisputeSerializer
    pagination_class = PanelPagination

    def get_queryset(self):
        qs = Dispute.objects.select_related('match', 'match__creator', 'match__joiner', 'assigned_to')
        scope = self.request.query_params.get('scope', '')
        status_f = self.request.query_params.get('status', '')
        if scope == 'mine':
            qs = qs.filter(assigned_to=self.request.user)
        if status_f:
            qs = qs.filter(status=status_f)
        return qs.order_by('-created_at')


class PanelDisputeDetailView(APIView):
    permission_classes = [IsSupportStaff]

    def get(self, request, dispute_id):
        dispute = get_object_or_404(
            Dispute.objects.select_related('match', 'match__creator', 'match__joiner', 'assigned_to'),
            id=dispute_id,
        )
        return Response(PanelDisputeDetailSerializer(dispute, context={'request': request}).data)


class PanelDisputeAttendView(APIView):
    permission_classes = [IsSupportStaff]

    @transaction.atomic
    def post(self, request, dispute_id):
        dispute = get_object_or_404(Dispute, id=dispute_id)
        if dispute.status != 'OPEN':
            return Response({'detail': 'This dispute is already assigned or resolved.'}, status=400)
        dispute.assigned_to = request.user
        dispute.status = 'PENDING'
        dispute.save(update_fields=['assigned_to', 'status'])
        return Response(PanelDisputeSerializer(dispute).data)


class PanelDisputeResolveView(APIView):
    permission_classes = [IsSupportStaff]

    @transaction.atomic
    def post(self, request, dispute_id):
        dispute = get_object_or_404(Dispute, id=dispute_id)
        match = dispute.match
        winner_id = request.data.get('winner_id')
        notes = request.data.get('resolution_notes', '')
        if not winner_id:
            return Response({'detail': 'Please select a winner.'}, status=400)
        if str(winner_id) not in [str(match.creator_id), str(match.joiner_id)]:
            return Response({'detail': 'Invalid winner.'}, status=400)
        winner = get_object_or_404(User, id=winner_id)
        wallet, _ = Wallet.objects.get_or_create(user=winner)
        wallet.balance += match.winnings
        wallet.save(update_fields=['balance'])
        Transaction.objects.create(
            wallet=wallet,
            amount=match.winnings,
            transaction_type='MATCH_WINNINGS',
            description=f"Winnings from resolving {match.get_game_display()} dispute",
        )
        Notification.objects.create(
            user=match.creator,
            message=f"Dispute for {match.get_game_display()} resolved. Winner: {winner.username}.",
        )
        if match.joiner:
            Notification.objects.create(
                user=match.joiner,
                message=f"Dispute for {match.get_game_display()} resolved. Winner: {winner.username}.",
            )
        match.status = 'COMPLETED'
        match.winner = winner
        match.save(update_fields=['status', 'winner'])
        # Referral commission on the realised platform fee (admin-awarded settlement)
        from matches.views import _accrue_match_commissions
        _accrue_match_commissions(match)
        dispute.status = 'RESOLVED'
        dispute.resolved_at = timezone.now()
        dispute.resolution_notes = notes
        dispute.save(update_fields=['status', 'resolved_at', 'resolution_notes'])
        return Response(PanelDisputeSerializer(dispute).data)


class PanelDisputeEscalateView(APIView):
    permission_classes = [IsSupportStaff]

    @transaction.atomic
    def post(self, request, dispute_id):
        dispute = get_object_or_404(Dispute, id=dispute_id)
        if dispute.status == 'RESOLVED':
            return Response({'detail': 'Cannot escalate a resolved dispute.'}, status=400)
        dispute.status = 'ESCALATED'
        dispute.escalated_at = timezone.now()
        dispute.escalated_by = request.user
        dispute.escalation_reason = request.data.get('escalation_reason', '')
        dispute.save(update_fields=['status', 'escalated_at', 'escalated_by', 'escalation_reason'])
        return Response(PanelDisputeSerializer(dispute).data)


class PanelDisputeSuspendUserView(APIView):
    permission_classes = [IsSupportStaff]

    @transaction.atomic
    def post(self, request, dispute_id):
        dispute = get_object_or_404(Dispute, id=dispute_id)
        user_id = request.data.get('user_id')
        user = get_object_or_404(User, id=user_id)
        if user.is_superuser:
            return Response({'detail': 'Cannot suspend a superuser account.'}, status=400)
        if not user.is_active:
            return Response({'detail': 'User is already suspended.', 'is_active': False}, status=200)
        user.is_active = False
        user.save(update_fields=['is_active'])
        return Response({'message': f'{user.username} suspended.', 'is_active': False})


class PanelDisputeStatsView(APIView):
    permission_classes = [IsSupportStaff]

    def get(self, request):
        stats = (
            User.objects.filter(
                Q(created_matches__dispute__isnull=False) | Q(joined_matches__dispute__isnull=False)
            )
            .distinct()
            .annotate(
                total_disputes=Count('created_matches__dispute', distinct=True) +
                               Count('joined_matches__dispute', distinct=True),
                open_disputes=Count('created_matches__dispute', filter=Q(created_matches__dispute__status='OPEN'), distinct=True) +
                              Count('joined_matches__dispute', filter=Q(joined_matches__dispute__status='OPEN'), distinct=True),
                pending_disputes=Count('created_matches__dispute', filter=Q(created_matches__dispute__status='PENDING'), distinct=True) +
                                 Count('joined_matches__dispute', filter=Q(joined_matches__dispute__status='PENDING'), distinct=True),
                resolved_disputes=Count('created_matches__dispute', filter=Q(created_matches__dispute__status='RESOLVED'), distinct=True) +
                                  Count('joined_matches__dispute', filter=Q(joined_matches__dispute__status='RESOLVED'), distinct=True),
            )
            .order_by('-total_disputes', 'username')
            .values('id', 'username', 'total_disputes', 'open_disputes', 'pending_disputes', 'resolved_disputes')
        )
        return Response(list(stats))


# ---------------------------------------------------------------- Payment gateway
# Deposit methods available per active provider (mirrors DepositCreateSerializer.validate).
GATEWAY_DEPOSIT_METHODS = {
    'lipila': [
        {'value': 'LIPILA_MOMO', 'label': 'Lipila Mobile Money'},
        {'value': 'LIPILA', 'label': 'Lipila (Card / Bank)'},
    ],
    'zynle': [
        {'value': 'ZYNLE_MOMO', 'label': 'Zynle Mobile Money'},
    ],
}
GATEWAY_CHOICES = [
    {'value': 'lipila', 'label': 'Lipila'},
    {'value': 'zynle', 'label': 'ZynlePay'},
]


def _gateway_payload():
    from wallet.models import PaymentGatewaySetting
    setting, _ = PaymentGatewaySetting.objects.get_or_create(pk=1)
    provider = setting.active_provider
    return {
        'active_provider': provider,
        'choices': GATEWAY_CHOICES,
        'deposit_methods': GATEWAY_DEPOSIT_METHODS.get(provider, []),
        'updated_at': setting.updated_at,
    }


class PanelPaymentGatewayView(APIView):
    """GET/POST the active deposit gateway (admin only)."""
    permission_classes = [IsSupportStaff]

    def get(self, request):
        return Response(_gateway_payload())

    def post(self, request):
        from wallet.models import PaymentGatewaySetting
        provider = str(request.data.get('active_provider', '')).strip().lower()
        valid = {c['value'] for c in GATEWAY_CHOICES}
        if provider not in valid:
            return Response(
                {'detail': f"Invalid provider. Choose one of: {', '.join(sorted(valid))}."},
                status=400,
            )
        setting, _ = PaymentGatewaySetting.objects.get_or_create(pk=1)
        setting.active_provider = provider
        setting.save()
        return Response(_gateway_payload())


class ActivePaymentGatewayView(APIView):
    """Read-only active gateway + valid deposit methods for the deposit form (any user)."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        payload = _gateway_payload()
        return Response({
            'active_provider': payload['active_provider'],
            'deposit_methods': payload['deposit_methods'],
        })


# ---------------------------------------------------------------- Trend (monthly)
class PanelStatsTrendView(APIView):
    """Monthly counts for the given year and the year before, for the dashboard chart."""
    permission_classes = [IsSupportStaff]

    def get(self, request):
        from django.db.models.functions import ExtractMonth
        try:
            year = int(request.query_params.get('year') or timezone.now().year)
        except (TypeError, ValueError):
            year = timezone.now().year
        prev = year - 1

        def monthly(model, date_field, yr):
            rows = (
                model.objects.filter(**{f'{date_field}__year': yr})
                .annotate(m=ExtractMonth(date_field))
                .values('m').annotate(c=Count('id'))
            )
            counts = {r['m']: r['c'] for r in rows}
            return [counts.get(i, 0) for i in range(1, 13)]

        return Response({
            'year': year,
            'previous_year': prev,
            'metrics': {
                'matches': {'label': 'Matches created', 'current': monthly(Match, 'created_at', year), 'previous': monthly(Match, 'created_at', prev)},
                'disputes': {'label': 'Disputes opened', 'current': monthly(Dispute, 'created_at', year), 'previous': monthly(Dispute, 'created_at', prev)},
                'users': {'label': 'New players', 'current': monthly(User, 'date_joined', year), 'previous': monthly(User, 'date_joined', prev)},
            },
        })


# ---------------------------------------------------------------- Finance / earnings
class PanelFinanceView(APIView):
    """Platform earnings (10% commission) vs money held on behalf of players."""
    permission_classes = [IsSupportStaff]

    def get(self, request):
        from django.db.models import Sum, F

        def txn_sum(ttype):
            return Transaction.objects.filter(transaction_type=ttype).aggregate(s=Sum('amount'))['s'] or Decimal('0')

        deposit = txn_sum('DEPOSIT')                  # +
        withdrawal = txn_sum('WITHDRAWAL')            # - (negative)
        creation = txn_sum('MATCH_CREATION')          # -
        joining = txn_sum('MATCH_JOINING')            # -
        winnings = txn_sum('MATCH_WINNINGS')          # +
        draw = txn_sum('MATCH_DRAW_RETURN')           # +
        refund = txn_sum('MATCH_REFUND')              # +

        staked = -(creation + joining)                # money staked out of player wallets (positive)
        returned = winnings + draw + refund           # money paid back to players (positive)

        # Money still locked in unresolved matches (not yet earnings, not withdrawable).
        open_escrow = Match.objects.filter(status='OPEN').aggregate(s=Sum('amount'))['s'] or Decimal('0')
        active_escrow = Match.objects.filter(status__in=['JOINED', 'DISPUTED']).aggregate(s=Sum('amount'))['s'] or Decimal('0')
        locked_escrow = Decimal(open_escrow) + Decimal(active_escrow) * 2  # OPEN=1 stake, JOINED/DISPUTED=2 stakes

        platform_earnings = staked - returned - locked_escrow

        player_wallets = Wallet.objects.aggregate(s=Sum('balance'))['s'] or Decimal('0')
        pending_withdrawals = Withdrawal.objects.filter(status__in=['PENDING', 'PROCESSING']).aggregate(s=Sum('amount'))['s'] or Decimal('0')
        held_for_players = Decimal(player_wallets) + locked_escrow + Decimal(pending_withdrawals)

        completed = Match.objects.filter(status='COMPLETED', winner__isnull=False)
        commission_settled = completed.aggregate(s=Sum(F('amount') * 2 - F('winnings')))['s'] or Decimal('0')

        def d(x):
            return str(Decimal(x).quantize(Decimal('0.01')))

        return Response({
            'platform_earnings': d(platform_earnings),
            'held_for_players': d(held_for_players),
            'breakdown': {
                'total_deposited': d(deposit),
                'total_withdrawn': d(-withdrawal),
                'player_wallet_balances': d(player_wallets),
                'locked_in_active_matches': d(locked_escrow),
                'pending_withdrawals': d(pending_withdrawals),
                'commission_from_settled_matches': d(commission_settled),
                'matches_settled': completed.count(),
                'total_staked': d(staked),
                'total_paid_out': d(returned),
            },
        })


# ---------------------------------------------------------------- Players leaderboard
class PanelPlayersView(APIView):
    """Per-player stats + leaderboard: games played/won/lost/drawn, winnings, deposits, withdrawals."""
    permission_classes = [IsSupportStaff]

    def get(self, request):
        from django.db.models import Sum
        from collections import defaultdict

        # --- match results (played / won / lost / draw) ---
        rec = defaultdict(lambda: {'played': 0, 'won': 0, 'lost': 0, 'draw': 0})
        draw_match_ids = set(
            Transaction.objects.filter(transaction_type='MATCH_DRAW_RETURN', related_match__isnull=False)
            .values_list('related_match_id', flat=True)
        )
        matches = Match.objects.filter(status__in=['JOINED', 'COMPLETED', 'DISPUTED']).values(
            'id', 'creator_id', 'joiner_id', 'winner_id'
        )
        for m in matches:
            participants = [p for p in (m['creator_id'], m['joiner_id']) if p]
            for p in participants:
                rec[p]['played'] += 1
            if m['id'] in draw_match_ids:
                for p in participants:
                    rec[p]['draw'] += 1
            elif m['winner_id']:
                rec[m['winner_id']]['won'] += 1
                for p in participants:
                    if p != m['winner_id']:
                        rec[p]['lost'] += 1

        # --- money per user (via transactions) ---
        def per_user(ttype):
            return {
                r['wallet__user']: r['s'] or Decimal('0')
                for r in Transaction.objects.filter(transaction_type=ttype)
                .values('wallet__user').annotate(s=Sum('amount'))
            }
        deposits = per_user('DEPOSIT')
        withdrawals = per_user('WITHDRAWAL')   # negative
        winnings = per_user('MATCH_WINNINGS')
        balances = {r['user_id']: r['balance'] for r in Wallet.objects.values('user_id', 'balance')}

        # --- assemble rows ---
        q = (request.query_params.get('q') or '').strip().lower()
        status_f = request.query_params.get('status', '')
        has_played = request.query_params.get('has_played', '')
        users = User.objects.all().values('id', 'username', 'is_active')
        rows = []
        for u in users:
            uid = u['id']
            if q and q not in u['username'].lower():
                continue
            if status_f == 'active' and not u['is_active']:
                continue
            if status_f == 'disabled' and u['is_active']:
                continue
            r = rec.get(uid, {'played': 0, 'won': 0, 'lost': 0, 'draw': 0})
            if has_played in ('1', 'true') and r['played'] == 0:
                continue
            decided = r['won'] + r['lost'] + r['draw']
            win_rate = round(100 * r['won'] / decided, 1) if decided else 0.0
            rows.append({
                'id': uid,
                'username': u['username'],
                'is_active': u['is_active'],
                'played': r['played'],
                'won': r['won'],
                'lost': r['lost'],
                'draw': r['draw'],
                'win_rate': win_rate,
                'winnings': str(Decimal(winnings.get(uid, 0)).quantize(Decimal('0.01'))),
                'deposited': str(Decimal(deposits.get(uid, 0)).quantize(Decimal('0.01'))),
                'withdrawn': str((-Decimal(withdrawals.get(uid, 0))).quantize(Decimal('0.01'))),
                'balance': str(Decimal(balances.get(uid, 0)).quantize(Decimal('0.01'))),
            })

        # --- sort ---
        ordering = request.query_params.get('ordering') or 'winnings'
        numeric = {'played', 'won', 'lost', 'draw', 'win_rate', 'winnings', 'deposited', 'withdrawn', 'balance'}
        if ordering == 'username':
            rows.sort(key=lambda x: x['username'].lower())
        elif ordering in numeric:
            rows.sort(key=lambda x: float(x[ordering]), reverse=True)

        # --- paginate ---
        try:
            page = max(1, int(request.query_params.get('page') or 1))
        except ValueError:
            page = 1
        page_size = 25
        count = len(rows)
        start = (page - 1) * page_size
        return Response({
            'count': count,
            'next': None if start + page_size >= count else page + 1,
            'previous': None if page <= 1 else page - 1,
            'results': rows[start:start + page_size],
        })


class PanelPlayerDetailView(APIView):
    """Full profile for one player: stats, match history (with outcome), transactions, disputes."""
    permission_classes = [IsSupportStaff]

    def get(self, request, user_id):
        from django.db.models import Sum, Q

        user = get_object_or_404(User, id=user_id)
        wallet, _ = Wallet.objects.get_or_create(user=user)

        draw_match_ids = set(
            Transaction.objects.filter(transaction_type='MATCH_DRAW_RETURN', related_match__isnull=False)
            .values_list('related_match_id', flat=True)
        )

        matches_qs = (
            Match.objects.filter(Q(creator=user) | Q(joiner=user))
            .select_related('creator', 'joiner', 'winner')
            .order_by('-created_at')
        )

        played = won = lost = draw = 0
        match_rows = []
        for m in matches_qs:
            if m.id in draw_match_ids:
                outcome = 'DRAW'
            elif m.winner_id == user.id:
                outcome = 'WON'
            elif m.winner_id and m.winner_id != user.id:
                outcome = 'LOST'
            elif m.status in ('OPEN', 'JOINED', 'DISPUTED'):
                outcome = 'PENDING'
            else:
                outcome = 'NA'

            if m.status in ('JOINED', 'COMPLETED', 'DISPUTED'):
                played += 1
                if outcome == 'WON':
                    won += 1
                elif outcome == 'LOST':
                    lost += 1
                elif outcome == 'DRAW':
                    draw += 1

            data = PanelMatchSerializer(m).data
            data['outcome'] = outcome
            data['role'] = 'creator' if m.creator_id == user.id else 'joiner'
            match_rows.append(data)

        decided = won + lost + draw
        win_rate = round(100 * won / decided, 1) if decided else 0.0

        def money(ttype):
            return Transaction.objects.filter(wallet=wallet, transaction_type=ttype).aggregate(s=Sum('amount'))['s'] or Decimal('0')

        deposited = money('DEPOSIT')
        withdrawn = -money('WITHDRAWAL')
        winnings = money('MATCH_WINNINGS')

        transactions = Transaction.objects.filter(wallet=wallet).select_related('wallet__user').order_by('-created_at')[:100]
        disputes = (
            Dispute.objects.filter(Q(match__creator=user) | Q(match__joiner=user))
            .select_related('match', 'match__creator', 'match__joiner', 'assigned_to')
            .order_by('-created_at')
        )

        return Response({
            'profile': {
                'id': user.id,
                'wallet_id': wallet.id,
                'username': user.username,
                'email': user.email,
                'date_joined': user.date_joined,
                'is_active': user.is_active,
                'is_support_staff': user.is_support_staff,
                'is_staff': user.is_staff,
                'is_superuser': user.is_superuser,
                'balance': str(wallet.balance),
            },
            'stats': {
                'played': played, 'won': won, 'lost': lost, 'draw': draw, 'win_rate': win_rate,
                'winnings': str(Decimal(winnings).quantize(Decimal('0.01'))),
                'deposited': str(Decimal(deposited).quantize(Decimal('0.01'))),
                'withdrawn': str(Decimal(withdrawn).quantize(Decimal('0.01'))),
                'balance': str(wallet.balance),
            },
            'matches': match_rows,
            'transactions': PanelTransactionSerializer(transactions, many=True).data,
            'disputes': PanelDisputeSerializer(disputes, many=True).data,
        })


# ---------------------------------------------------------------- Audit log
class PanelAuditLogView(APIView):
    """Paginated audit trail with action/user/text filters."""
    permission_classes = [IsSupportStaff]

    def get(self, request):
        import json
        from audit.models import AuditLog

        qs = AuditLog.objects.select_related('user').all()
        action = request.query_params.get('action', '')
        q = (request.query_params.get('q') or '').strip()
        user_id = request.query_params.get('user')
        if action:
            qs = qs.filter(action=action)
        if user_id:
            qs = qs.filter(user_id=user_id)
        if q:
            qs = qs.filter(Q(user__username__icontains=q) | Q(action__icontains=q) | Q(details__icontains=q))

        try:
            page = max(1, int(request.query_params.get('page') or 1))
        except ValueError:
            page = 1
        page_size = 30
        count = qs.count()
        start = (page - 1) * page_size
        rows = []
        for log in qs[start:start + page_size]:
            try:
                details = json.loads(log.details) if log.details else {}
            except (ValueError, TypeError):
                details = log.details
            rows.append({
                'id': log.id,
                'action': log.action,
                'username': log.user.username if log.user else 'System',
                'user_id': log.user_id,
                'timestamp': log.timestamp,
                'ip_address': log.ip_address,
                'user_agent': log.user_agent,
                'details': details,
            })

        actions = list(AuditLog.objects.values_list('action', flat=True).distinct().order_by('action'))
        return Response({
            'count': count,
            'next': None if start + page_size >= count else page + 1,
            'previous': None if page <= 1 else page - 1,
            'results': rows,
            'actions': actions,
        })


# ---------------------------------------------------------------- Wallet integrity
class PanelWalletIntegrityView(APIView):
    """List wallets whose balance != sum of transactions; reconcile all."""
    permission_classes = [IsSupportStaff]

    def get(self, request):
        discrepancies = Wallet.find_wallets_with_discrepancies().select_related('user')
        rows = []
        total_gap = Decimal('0')
        for w in discrepancies:
            res = w.verify_balance_integrity()
            gap = res['discrepancy']
            total_gap += abs(gap)
            rows.append({
                'wallet_id': w.id,
                'username': w.user.username,
                'actual_balance': str(res['actual_balance']),
                'expected_balance': str(res['expected_balance']),
                'discrepancy': str(gap),
                'transaction_count': res['transaction_count'],
            })
        return Response({
            'total_wallets': Wallet.objects.count(),
            'discrepancy_count': len(rows),
            'total_discrepancy': str(total_gap),
            'results': rows,
        })

    def post(self, request):
        """Reconcile all wallets (recalculate balances from transactions)."""
        result = Wallet.reconcile_all_wallets(dry_run=False)
        return Response({
            'message': f"Reconciled {result['wallets_fixed']} of {result['wallets_with_discrepancies']} flagged wallets.",
            'total_wallets': result['total_wallets'],
            'wallets_fixed': result['wallets_fixed'],
        })


# ---------------------------------------------------------------- Risk / suspicious activity
class PanelRiskView(APIView):
    """Recompute fraud/risk signals from wallet, withdrawal, deposit and audit data."""
    permission_classes = [IsSupportStaff]

    def get(self, request):
        import json
        from collections import defaultdict
        from audit.models import AuditLog

        LARGE = Decimal('5000.00')

        usernames = dict(User.objects.values_list('id', 'username'))

        # 1) Withdrawals the live fraud detector flagged (from audit log)
        flagged = []
        for log in AuditLog.objects.filter(action='withdrawal_created').order_by('-timestamp')[:500]:
            try:
                d = json.loads(log.details) if log.details else {}
            except (ValueError, TypeError):
                d = {}
            if isinstance(d, dict) and d.get('suspicious'):
                flagged.append({
                    'withdrawal_id': d.get('withdrawal_id'),
                    'username': log.user.username if log.user else 'System',
                    'amount': d.get('amount'),
                    'payment_method': d.get('payment_method'),
                    'ip_address': log.ip_address or d.get('ip_address'),
                    'timestamp': log.timestamp,
                })

        # 2) Large withdrawals
        large = [{
            'withdrawal_id': w.id, 'username': w.user.username, 'amount': str(w.amount),
            'status': w.status, 'payment_method': w.payment_method, 'created_at': w.created_at,
        } for w in Withdrawal.objects.filter(amount__gte=LARGE).select_related('user').order_by('-created_at')[:50]]

        # 3) Shared IPs — same IP used by multiple accounts (multi-accounting)
        ip_users = defaultdict(set)
        for ip, uid in Withdrawal.objects.exclude(ip_address__isnull=True).values_list('ip_address', 'user_id'):
            ip_users[ip].add(uid)
        for ip, uid in Deposit.objects.exclude(ip_address__isnull=True).values_list('ip_address', 'user_id'):
            ip_users[ip].add(uid)
        shared_ips = sorted(
            [{'ip_address': ip, 'user_count': len(uids), 'users': [usernames.get(u, f'#{u}') for u in list(uids)[:12]]}
             for ip, uids in ip_users.items() if len(uids) > 1],
            key=lambda x: x['user_count'], reverse=True,
        )[:50]

        # 4) Users withdrawing from many distinct IPs (possible account compromise)
        user_ips = defaultdict(set)
        for uid, ip in Withdrawal.objects.exclude(ip_address__isnull=True).values_list('user_id', 'ip_address'):
            user_ips[uid].add(ip)
        multi_ip = sorted(
            [{'user_id': uid, 'username': usernames.get(uid, f'#{uid}'), 'ip_count': len(ips)}
             for uid, ips in user_ips.items() if len(ips) > 2],
            key=lambda x: x['ip_count'], reverse=True,
        )[:50]

        disc_count = Wallet.find_wallets_with_discrepancies().count()

        return Response({
            'summary': {
                'flagged_withdrawals': len(flagged),
                'large_withdrawals': len(large),
                'shared_ip_clusters': len(shared_ips),
                'multi_ip_users': len(multi_ip),
                'wallet_discrepancies': disc_count,
                'large_threshold': str(LARGE),
            },
            'flagged_withdrawals': flagged[:50],
            'large_withdrawals': large,
            'shared_ips': shared_ips,
            'multi_ip_users': multi_ip,
        })


# ================================================================ Money operations
class PanelReportsView(APIView):
    """Daily deposits vs withdrawals, net cash flow and commission earned."""
    permission_classes = [IsSupportStaff]

    def get(self, request):
        from collections import defaultdict
        try:
            days = min(365, max(7, int(request.query_params.get('days') or 30)))
        except ValueError:
            days = 30
        start = timezone.now() - timedelta(days=days)

        buckets = defaultdict(lambda: {'deposits': Decimal('0'), 'withdrawals': Decimal('0'), 'commission': Decimal('0')})
        txns = (
            Transaction.objects.filter(created_at__gte=start)
            .select_related('related_match')
            .values('transaction_type', 'amount', 'created_at',
                    'related_match__amount', 'related_match__winnings')
        )
        for t in txns:
            day = timezone.localtime(t['created_at']).date().isoformat()
            b = buckets[day]
            tt = t['transaction_type']
            amt = Decimal(t['amount'])
            if tt == 'DEPOSIT':
                b['deposits'] += amt
            elif tt == 'WITHDRAWAL':
                b['withdrawals'] += -amt
            elif tt == 'MATCH_WINNINGS' and t['related_match__amount'] is not None:
                b['commission'] += Decimal(t['related_match__amount']) * 2 - Decimal(t['related_match__winnings'])
            elif tt == 'MATCH_DRAW_RETURN' and t['related_match__amount'] is not None:
                b['commission'] += Decimal(t['related_match__amount']) - amt

        series = []
        for i in range(days, -1, -1):
            day = (timezone.now() - timedelta(days=i)).date().isoformat()
            b = buckets.get(day, {'deposits': Decimal('0'), 'withdrawals': Decimal('0'), 'commission': Decimal('0')})
            series.append({
                'date': day,
                'deposits': str(b['deposits'].quantize(Decimal('0.01'))),
                'withdrawals': str(b['withdrawals'].quantize(Decimal('0.01'))),
                'net': str((b['deposits'] - b['withdrawals']).quantize(Decimal('0.01'))),
                'commission': str(b['commission'].quantize(Decimal('0.01'))),
            })

        pending_liability = Withdrawal.objects.filter(status__in=['PENDING', 'PROCESSING']).aggregate(s=Sum('amount'))['s'] or Decimal('0')
        totals = {
            'deposits': str(sum((Decimal(r['deposits']) for r in series), Decimal('0')).quantize(Decimal('0.01'))),
            'withdrawals': str(sum((Decimal(r['withdrawals']) for r in series), Decimal('0')).quantize(Decimal('0.01'))),
            'commission': str(sum((Decimal(r['commission']) for r in series), Decimal('0')).quantize(Decimal('0.01'))),
            'net': str(sum((Decimal(r['net']) for r in series), Decimal('0')).quantize(Decimal('0.01'))),
            'pending_payout_liability': str(Decimal(pending_liability).quantize(Decimal('0.01'))),
        }
        return Response({'days': days, 'series': series, 'totals': totals})


class PanelWalletAdjustView(APIView):
    """Manually credit or debit a player's wallet, with a required reason (audited)."""
    permission_classes = [IsSupportStaff]

    @transaction.atomic
    def post(self, request, wallet_id):
        from audit.utils import log_action
        wallet = get_object_or_404(Wallet.objects.select_related('user'), id=wallet_id)
        reason = (request.data.get('reason') or '').strip()
        if not reason:
            return Response({'detail': 'A reason is required for manual adjustments.'}, status=400)
        try:
            amount = Decimal(str(request.data.get('amount')))
        except Exception:
            return Response({'detail': 'Invalid amount.'}, status=400)
        if amount == 0:
            return Response({'detail': 'Amount cannot be zero.'}, status=400)
        old_balance = wallet.balance
        new_balance = old_balance + amount
        if new_balance < 0:
            return Response({'detail': f'Debit exceeds balance (ZMW {old_balance}).'}, status=400)

        wallet.balance = new_balance
        wallet.save(update_fields=['balance'])
        Transaction.objects.create(
            wallet=wallet,
            amount=amount,
            transaction_type='OTHER',
            description=f"Manual {'credit' if amount > 0 else 'debit'} by {request.user.username}: {reason}",
        )
        log_action(
            action='wallet_manual_adjustment',
            user=request.user,
            details={
                'wallet_id': wallet.id, 'target_user': wallet.user.username,
                'amount': str(amount), 'reason': reason,
                'old_balance': str(old_balance), 'new_balance': str(new_balance),
            },
            request=request,
        )
        return Response({'message': 'Wallet adjusted.', 'old_balance': str(old_balance), 'new_balance': str(new_balance)})


# ================================================================ Analytics
class PanelAnalyticsView(APIView):
    """Per-game analytics + growth/retention metrics."""
    permission_classes = [IsSupportStaff]

    def get(self, request):
        from collections import defaultdict
        draw_ids = set(
            Transaction.objects.filter(transaction_type='MATCH_DRAW_RETURN', related_match__isnull=False)
            .values_list('related_match_id', flat=True)
        )
        games = defaultdict(lambda: {'total': 0, 'played': 0, 'abandoned': 0, 'wins': 0, 'draws': 0,
                                     'staked': Decimal('0'), 'revenue': Decimal('0')})
        for m in Match.objects.values('id', 'game', 'status', 'joiner_id', 'winner_id', 'amount', 'winnings'):
            g = games[m['game']]
            g['total'] += 1
            g['staked'] += Decimal(m['amount'])
            if m['status'] == 'OPEN' and not m['joiner_id']:
                g['abandoned'] += 1
            if m['status'] in ('JOINED', 'COMPLETED', 'DISPUTED'):
                g['played'] += 1
            if m['id'] in draw_ids:
                g['draws'] += 1
                g['revenue'] += Decimal(m['amount']) * 2 - Decimal(m['amount'] * 2 * 90 // 100)
            elif m['winner_id']:
                g['wins'] += 1
                g['revenue'] += Decimal(m['amount']) * 2 - Decimal(m['winnings'])

        game_rows = []
        for game, g in games.items():
            decided = g['wins'] + g['draws']
            game_rows.append({
                'game': game,
                'total': g['total'], 'played': g['played'], 'abandoned': g['abandoned'],
                'wins': g['wins'], 'draws': g['draws'],
                'avg_stake': str((g['staked'] / g['total']).quantize(Decimal('0.01'))) if g['total'] else '0.00',
                'revenue': str(g['revenue'].quantize(Decimal('0.01'))),
                'win_rate': round(100 * g['wins'] / decided, 1) if decided else 0.0,
                'draw_rate': round(100 * g['draws'] / decided, 1) if decided else 0.0,
            })
        game_rows.sort(key=lambda x: x['played'], reverse=True)

        # Growth
        month_start = timezone.now() - timedelta(days=30)
        day_start = timezone.now() - timedelta(days=1)
        total_users = User.objects.count()

        def active_since(since):
            a = set(Transaction.objects.filter(created_at__gte=since).values_list('wallet__user_id', flat=True))
            for uid1, uid2 in Match.objects.filter(created_at__gte=since).values_list('creator_id', 'joiner_id'):
                a.add(uid1)
                if uid2:
                    a.add(uid2)
            a.discard(None)
            return a

        mau = len(active_since(month_start))
        dau = len(active_since(day_start))
        depositors = Transaction.objects.filter(transaction_type='DEPOSIT').values('wallet__user').distinct().count()

        signup_buckets = defaultdict(int)
        for dj in User.objects.filter(date_joined__gte=month_start).values_list('date_joined', flat=True):
            signup_buckets[timezone.localtime(dj).date().isoformat()] += 1
        signups = []
        for i in range(30, -1, -1):
            day = (timezone.now() - timedelta(days=i)).date().isoformat()
            signups.append({'date': day, 'count': signup_buckets.get(day, 0)})

        growth = {
            'total_users': total_users,
            'mau': mau, 'dau': dau,
            'depositors': depositors,
            'deposit_conversion': round(100 * depositors / total_users, 1) if total_users else 0.0,
            'signups': signups,
            'new_last_30d': sum(s['count'] for s in signups),
        }
        return Response({'games': game_rows, 'growth': growth})


class PanelStuckMatchesView(APIView):
    """Matches stuck in JOINED with no result for longer than N hours."""
    permission_classes = [IsSupportStaff]

    def get(self, request):
        try:
            hours = max(1, int(request.query_params.get('hours') or 6))
        except ValueError:
            hours = 6
        cutoff = timezone.now() - timedelta(hours=hours)
        qs = (Match.objects.filter(status='JOINED', created_at__lte=cutoff)
              .select_related('creator', 'joiner').order_by('created_at'))
        rows = []
        now = timezone.now()
        for m in qs[:200]:
            age_h = round((now - m.created_at).total_seconds() / 3600, 1)
            rows.append({
                'id': m.id, 'game': m.get_game_display(), 'amount': m.amount,
                'creator': m.creator.username, 'joiner': m.joiner.username if m.joiner else None,
                'created_at': m.created_at, 'age_hours': age_h,
            })
        return Response({'hours': hours, 'count': len(rows), 'results': rows})


# ================================================================ Comms
class PanelBroadcastView(APIView):
    """Send a notification to one player or everyone."""
    permission_classes = [IsSupportStaff]

    def post(self, request):
        from audit.utils import log_action
        message = (request.data.get('message') or '').strip()
        link = (request.data.get('link') or '').strip() or None
        target = request.data.get('target', 'all')
        user_id = request.data.get('user_id')
        if not message:
            return Response({'detail': 'Message is required.'}, status=400)

        if target == 'user' and user_id:
            users = list(User.objects.filter(id=user_id))
        elif target == 'active':
            since = timezone.now() - timedelta(days=30)
            ids = set(Transaction.objects.filter(created_at__gte=since).values_list('wallet__user_id', flat=True))
            ids.discard(None)
            users = list(User.objects.filter(id__in=ids, is_active=True))
        else:
            users = list(User.objects.filter(is_active=True))

        Notification.objects.bulk_create([Notification(user=u, message=message, link=link) for u in users])
        log_action(action='broadcast_sent', user=request.user,
                   details={'target': target, 'recipients': len(users), 'message': message[:200]}, request=request)
        return Response({'message': f'Sent to {len(users)} player(s).', 'recipients': len(users)})


class PanelSupportRecentView(APIView):
    """Recent messages across the platform (monitoring feed)."""
    permission_classes = [IsSupportStaff]

    def get(self, request):
        from messenger.models import Message
        msgs = Message.objects.select_related('sender', 'receiver').order_by('-created_at')[:60]
        return Response({'results': [{
            'id': m.id, 'sender': m.sender.username, 'sender_id': m.sender_id,
            'receiver': m.receiver.username, 'receiver_id': m.receiver_id,
            'message': m.message, 'created_at': m.created_at,
        } for m in msgs]})


# ================================================================ Player management
class PanelPlayerActionView(APIView):
    """Admin actions on a player: staff role, password reset, ban/unban."""
    permission_classes = [IsSupportStaff]

    @transaction.atomic
    def post(self, request, user_id):
        from audit.utils import log_action
        from django.utils.crypto import get_random_string
        target = get_object_or_404(User, id=user_id)
        action = request.data.get('action')
        reason = (request.data.get('reason') or '').strip()

        if target.is_superuser and action in ('ban', 'remove_support', 'reset_password'):
            return Response({'detail': 'Cannot perform this action on a superuser.'}, status=400)
        if target.id == request.user.id and action == 'ban':
            return Response({'detail': 'You cannot ban your own account.'}, status=400)

        result = {}
        if action == 'make_support':
            target.is_support_staff = True
            target.save(update_fields=['is_support_staff'])
            result['message'] = f'{target.username} is now support staff.'
        elif action == 'remove_support':
            target.is_support_staff = False
            target.save(update_fields=['is_support_staff'])
            result['message'] = f'{target.username} is no longer support staff.'
        elif action == 'ban':
            if not reason:
                return Response({'detail': 'A reason is required to ban a player.'}, status=400)
            target.is_active = False
            target.save(update_fields=['is_active'])
            result['message'] = f'{target.username} has been banned.'
        elif action == 'unban':
            target.is_active = True
            target.save(update_fields=['is_active'])
            result['message'] = f'{target.username} has been reinstated.'
        elif action == 'reset_password':
            temp = get_random_string(10)
            target.set_password(temp)
            target.save(update_fields=['password'])
            result['message'] = f'Temporary password set for {target.username}.'
            result['temp_password'] = temp
        else:
            return Response({'detail': 'Unknown action.'}, status=400)

        log_action(action=f'player_{action}', user=request.user,
                   details={'target_user': target.username, 'target_id': target.id, 'reason': reason}, request=request)
        result['is_active'] = target.is_active
        result['is_support_staff'] = target.is_support_staff
        return Response(result)


# ---------------------------------------------------------------- Organisers
class PanelOrganisationListView(ListAPIView):
    """Directory of organisers on the platform with search and status filters."""
    permission_classes = [IsSupportStaff]
    serializer_class = PanelOrganisationSerializer
    pagination_class = PanelPagination

    def get_queryset(self):
        qs = (
            Organisation.objects
            .select_related('owner')
            .annotate(
                tournaments_count=Count('tournaments', distinct=True),
                active_tournaments_count=Count(
                    'tournaments',
                    filter=Q(tournaments__status__in=['OPEN', 'REG_CLOSED', 'SCHEDULED', 'LIVE', 'RESULTS_PENDING', 'PAYOUT_PROCESSING']),
                    distinct=True,
                ),
                members_count=Count(
                    'memberships',
                    filter=Q(memberships__status='APPROVED'),
                    distinct=True,
                ),
            )
            .order_by('-created_at')
        )
        q = self.request.query_params.get('q', '').strip()
        org_type = self.request.query_params.get('type', '')
        verified = self.request.query_params.get('verified', '')
        availability = self.request.query_params.get('availability', '')
        if q:
            qs = qs.filter(
                Q(name__icontains=q) |
                Q(email__icontains=q) |
                Q(contact_name__icontains=q) |
                Q(city__icontains=q)
            )
        if org_type:
            qs = qs.filter(organisation_type=org_type)
        if verified == 'verified':
            qs = qs.filter(is_verified=True)
        elif verified == 'unverified':
            qs = qs.filter(is_verified=False)
        if availability == 'available':
            qs = qs.filter(is_verified=True, owner__is_active=True)
        elif availability == 'unavailable':
            qs = qs.filter(Q(is_verified=False) | Q(owner__is_active=False))
        return qs


class PanelOrganisationDetailView(APIView):
    """Single organiser with its tournaments."""
    permission_classes = [IsSupportStaff]

    def get(self, request, org_id):
        org = get_object_or_404(Organisation.objects.select_related('owner'), id=org_id)
        return Response(PanelOrganisationDetailSerializer(org, context={'request': request}).data)


class PanelOrganisationVerifyView(APIView):
    """Verify or un-verify an organiser."""
    permission_classes = [IsSupportStaff]

    def post(self, request, org_id):
        org = get_object_or_404(Organisation.objects.select_related('owner'), id=org_id)
        action = request.data.get('action', 'verify')
        org.is_verified = (action == 'verify')
        org.save(update_fields=['is_verified', 'updated_at'])
        try:
            from audit.utils import log_action
            log_action(action=f'organisation_{action}', user=request.user,
                       details={'organisation': org.name, 'organisation_id': org.id}, request=request)
        except Exception:
            pass
        return Response(PanelOrganisationSerializer(org).data)


class PanelOrganisationToggleView(APIView):
    """Suspend or reactivate an organiser by toggling its owner account.
    A suspended owner makes the organiser unavailable on the platform."""
    permission_classes = [IsSupportStaff]

    def post(self, request, org_id):
        org = get_object_or_404(Organisation.objects.select_related('owner'), id=org_id)
        action = request.data.get('action', 'disable')
        owner = org.owner
        if action == 'disable':
            if owner.is_superuser:
                return Response({'detail': 'Cannot suspend a superuser account.'}, status=400)
            if owner.id == request.user.id:
                return Response({'detail': 'You cannot suspend your own account.'}, status=400)
            owner.is_active = False
        else:
            owner.is_active = True
        owner.save(update_fields=['is_active'])
        try:
            from audit.utils import log_action
            log_action(action=f'organisation_{"suspend" if action == "disable" else "reactivate"}',
                       user=request.user,
                       details={'organisation': org.name, 'organisation_id': org.id, 'owner': owner.username},
                       request=request)
        except Exception:
            pass
        return Response(PanelOrganisationSerializer(org).data)


# ---------------------------------------------------------------- Referrals
from referrals.models import (  # noqa: E402
    Referrer, ReferralCommissionLedger, ReferralTransfer,
)
from referrals import services as referral_services  # noqa: E402
from .panel_serializers import (  # noqa: E402
    PanelReferrerSerializer,
    PanelReferralTransferSerializer,
    PanelReferralLedgerSerializer,
)


class PanelReferrerListView(ListAPIView):
    """GET /api/panel/referrals/referrers/ — referrer applications & accounts."""
    permission_classes = [IsSupportStaff]
    serializer_class = PanelReferrerSerializer
    pagination_class = PanelPagination

    def get_queryset(self):
        qs = Referrer.objects.select_related("user").order_by("-created_at")
        status_f = self.request.query_params.get("status", "")
        q = self.request.query_params.get("q", "").strip()
        if status_f:
            qs = qs.filter(status=status_f)
        if q:
            qs = qs.filter(
                Q(referral_code__icontains=q) | Q(user__username__icontains=q)
            )
        return qs


class PanelReferrerActionView(APIView):
    """POST /api/panel/referrals/referrers/<id>/action/

    Body: {"action": "approve"|"suspend"|"reject", "commission_rate": <opt>}.
    """
    permission_classes = [IsSupportStaff]

    @transaction.atomic
    def post(self, request, referrer_id):
        referrer = get_object_or_404(Referrer, id=referrer_id)
        action = request.data.get("action")
        rate = request.data.get("commission_rate")

        status_map = {
            "approve": Referrer.Status.APPROVED,
            "suspend": Referrer.Status.SUSPENDED,
            "reject": Referrer.Status.REJECTED,
        }
        if action == "set_rate":
            if rate is None:
                return Response({"detail": "commission_rate is required."}, status=400)
        elif action not in status_map:
            return Response(
                {"detail": "Invalid action. Use approve, suspend, reject or set_rate."},
                status=400,
            )

        if action in status_map:
            referrer.status = status_map[action]
        if rate is not None:
            try:
                referrer.commission_rate = Decimal(str(rate))
            except (TypeError, ValueError):
                return Response({"detail": "Invalid commission_rate."}, status=400)
        referrer.save()

        if referrer.status == Referrer.Status.APPROVED:
            referral_services.get_or_create_referral_wallet(referrer.user)

        return Response(PanelReferrerSerializer(referrer).data)


class PanelReferralTransferListView(ListAPIView):
    """GET /api/panel/referrals/transfers/ — internal transfer audit trail."""
    permission_classes = [IsSupportStaff]
    serializer_class = PanelReferralTransferSerializer
    pagination_class = PanelPagination

    def get_queryset(self):
        qs = ReferralTransfer.objects.select_related(
            "referrer", "referrer__user", "commission", "wallet_transaction"
        ).order_by("-created_at")
        status_f = self.request.query_params.get("status", "")
        q = self.request.query_params.get("q", "").strip()
        if status_f:
            qs = qs.filter(status=status_f)
        if q:
            qs = qs.filter(
                referrer__user__username__icontains=q
            )
        return qs


class PanelReferralLedgerListView(ListAPIView):
    """GET /api/panel/referrals/ledger/ — full commission audit trail (read-only)."""
    permission_classes = [IsSupportStaff]
    serializer_class = PanelReferralLedgerSerializer
    pagination_class = PanelPagination

    def get_queryset(self):
        qs = ReferralCommissionLedger.objects.select_related(
            "referrer", "referred_user"
        ).order_by("-created_at")
        status_f = self.request.query_params.get("status", "")
        q = self.request.query_params.get("q", "").strip()
        if status_f:
            qs = qs.filter(status=status_f)
        if q:
            qs = qs.filter(
                Q(referrer__referral_code__icontains=q)
                | Q(referred_user__username__icontains=q)
            )
        return qs
