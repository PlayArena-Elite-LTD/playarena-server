"""DRF serializers for referral program endpoints."""
from rest_framework import serializers

from .models import (
    Referral,
    Referrer,
    ReferralCommissionLedger,
    ReferralTransfer,
    ReferralWallet,
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
    class Meta:
        model = ReferralWallet
        fields = ("balance", "available_balance", "pending_balance")
        read_only_fields = fields

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


class ReferralTransferSerializer(serializers.ModelSerializer):
    commission_id = serializers.IntegerField(read_only=True)
    wallet_transaction_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = ReferralTransfer
        fields = (
            "id",
            "commission_id",
            "wallet_transaction_id",
            "amount",
            "status",
            "transfer_reference",
            "created_at",
            "completed_at",
        )
        read_only_fields = fields
