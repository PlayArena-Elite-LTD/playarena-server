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
