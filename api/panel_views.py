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

from matches.models import Match, Evidence
from wallet.models import Wallet, Transaction, Deposit, Withdrawal
from panel.models import Dispute
from alert.models import Notification

from .panel_serializers import (
    PanelUserSerializer, PanelMatchSerializer, EvidenceSerializer,
    PanelWalletSerializer, PanelTransactionSerializer, PanelDepositSerializer,
    PanelWithdrawalSerializer, PanelDisputeSerializer, PanelDisputeDetailSerializer,
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
