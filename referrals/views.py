"""DRF endpoints for the referral program (player/referrer facing)."""
from rest_framework import generics, permissions, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    Referral,
    Referrer,
    ReferralCommissionLedger,
    ReferralWallet,
    ReferralWithdrawal,
)
from .serializers import (
    ReferredPlayerSerializer,
    ReferralLedgerSerializer,
    ReferralWalletSerializer,
    ReferralWithdrawalSerializer,
    ReferrerSerializer,
)


class LedgerPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 100


class ReferralApplyView(APIView):
    """POST /api/referrals/apply/ -> create a PENDING referrer for the user.

    Referral code defaults to the username (spec example: ``ref=KOSAMU``).
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        existing = getattr(request.user, "referrer", None)
        if existing is not None:
            return Response(
                ReferrerSerializer(existing).data, status=status.HTTP_200_OK
            )

        code = (request.data.get("referral_code") or request.user.username).strip()
        if Referrer.objects.filter(referral_code=code).exists():
            code = f"{request.user.username}{request.user.id}"

        referrer = Referrer.objects.create(user=request.user, referral_code=code)
        ReferralWallet.objects.get_or_create(user=request.user)
        return Response(
            ReferrerSerializer(referrer).data, status=status.HTTP_201_CREATED
        )


class ReferralMeView(generics.RetrieveAPIView):
    """GET /api/referrals/me/ -> the caller's referrer profile."""

    serializer_class = ReferrerSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        referrer = getattr(request.user, "referrer", None)
        if referrer is None:
            return Response(
                {"detail": "You are not a referrer yet.", "is_referrer": False},
                status=status.HTTP_200_OK,
            )
        return Response({**ReferrerSerializer(referrer).data, "is_referrer": True})


class ReferralWalletView(generics.RetrieveAPIView):
    """GET /api/referrals/wallet/ -> the caller's referral wallet."""

    serializer_class = ReferralWalletSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        wallet, _ = ReferralWallet.objects.get_or_create(user=self.request.user)
        return wallet


class ReferralLedgerView(generics.ListAPIView):
    """GET /api/referrals/ledger/ -> the caller's commission ledger."""

    serializer_class = ReferralLedgerSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = LedgerPagination

    def get_queryset(self):
        referrer = getattr(self.request.user, "referrer", None)
        if referrer is None:
            return ReferralCommissionLedger.objects.none()
        return referrer.ledger_entries.select_related("referred_user").all()


class ReferredPlayersView(generics.ListAPIView):
    """GET /api/referrals/referred/ -> players the caller referred."""

    serializer_class = ReferredPlayerSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        referrer = getattr(self.request.user, "referrer", None)
        if referrer is None:
            return Referral.objects.none()
        return referrer.referrals.select_related("referred_user").all()


class ReferralWithdrawalView(generics.ListCreateAPIView):
    """GET/POST /api/referrals/withdrawals/ -> list or request a payout."""

    serializer_class = ReferralWithdrawalSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        referrer = getattr(self.request.user, "referrer", None)
        if referrer is None:
            return ReferralWithdrawal.objects.none()
        return referrer.withdrawals.all()

    def perform_create(self, serializer):
        serializer.save(referrer=self.request.user.referrer)
