"""DRF serializers for referral program endpoints."""
from decimal import Decimal

from django.conf import settings
from rest_framework import serializers

from .models import (
    Referral,
    Referrer,
    ReferralCommissionLedger,
    ReferralWallet,
    ReferralWithdrawal,
)


class ReferrerSerializer(serializers.ModelSerializer):
    share_url = serializers.SerializerMethodField()

    class Meta:
        model = Referrer
        fields = (
            "id",
            "referral_code",
            "status",
            "commission_rate",
            "share_url",
            "created_at",
        )
        read_only_fields = fields

    def get_share_url(self, obj):
        return obj.share_url()


class ReferralWalletSerializer(serializers.ModelSerializer):
    available_balance = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )
    pending_balance = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )
    min_withdrawal = serializers.SerializerMethodField()

    class Meta:
        model = ReferralWallet
        fields = ("balance", "available_balance", "pending_balance", "min_withdrawal")
        read_only_fields = fields

    def get_min_withdrawal(self, obj):
        return Decimal(getattr(settings, "MIN_REFERRAL_WITHDRAWAL", Decimal("50.00")))


class ReferralLedgerSerializer(serializers.ModelSerializer):
    referred_username = serializers.CharField(
        source="referred_user.username", read_only=True
    )

    class Meta:
        model = ReferralCommissionLedger
        fields = (
            "id",
            "referred_username",
            "platform_fee",
            "commission_rate",
            "commission_amount",
            "status",
            "related_match",
            "related_tournament",
            "created_at",
        )
        read_only_fields = fields


class ReferredPlayerSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="referred_user.username", read_only=True)

    class Meta:
        model = Referral
        fields = ("username", "status", "created_at")
        read_only_fields = fields


class ReferralWithdrawalSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReferralWithdrawal
        fields = (
            "id",
            "amount",
            "status",
            "payment_reference",
            "created_at",
            "processed_at",
        )
        read_only_fields = (
            "id",
            "status",
            "payment_reference",
            "created_at",
            "processed_at",
        )

    def validate_amount(self, value):
        request = self.context["request"]
        referrer = getattr(request.user, "referrer", None)
        if referrer is None or referrer.status != Referrer.Status.APPROVED:
            raise serializers.ValidationError("You are not an approved referrer.")

        minimum = Decimal(getattr(settings, "MIN_REFERRAL_WITHDRAWAL", Decimal("50.00")))
        if value < minimum:
            raise serializers.ValidationError(
                f"Minimum referral withdrawal is ZMW {minimum}."
            )

        wallet, _ = ReferralWallet.objects.get_or_create(user=request.user)
        if value > wallet.available_balance:
            raise serializers.ValidationError(
                "Amount exceeds your available referral balance."
            )
        return value
