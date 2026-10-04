import decimal

import django.core.validators
import django.db.models.deletion
import referrals.models
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("referrals", "0001_initial"),
        ("wallet", "0014_referral_transfer_transaction_type"),
    ]

    operations = [
        # Preserve old payout rows as historical records; do not discard them.
        migrations.RenameModel(
            old_name="ReferralWithdrawal",
            new_name="LegacyReferralWithdrawal",
        ),
        migrations.AlterModelTable(
            name="legacyreferralwithdrawal",
            table="referrals_referralwithdrawal",
        ),
        migrations.AlterField(
            model_name="legacyreferralwithdrawal",
            name="referrer",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="legacy_withdrawals",
                to="referrals.referrer",
            ),
        ),
        migrations.AlterModelOptions(
            name="legacyreferralwithdrawal",
            options={
                "ordering": ["-created_at"],
                "verbose_name": "legacy referral payout record",
                "verbose_name_plural": "legacy referral payout records",
            },
        ),
        migrations.AlterField(
            model_name="referrer",
            name="commission_rate",
            field=models.DecimalField(
                decimal_places=2,
                default=referrals.models.default_commission_rate,
                help_text="Commission percentage earned from the platform fee.",
                max_digits=5,
                validators=[
                    django.core.validators.MinValueValidator(0),
                    django.core.validators.MaxValueValidator(100),
                ],
            ),
        ),
        migrations.AlterField(
            model_name="referral",
            name="referral_code",
            field=models.CharField(
                help_text="Referral code used during registration.",
                max_length=50,
            ),
        ),
        migrations.AlterField(
            model_name="referralcommissionledger",
            name="platform_fee",
            field=models.DecimalField(
                decimal_places=2,
                help_text="Platform fee on which the referral commission was calculated.",
                max_digits=12,
            ),
        ),
        migrations.AlterField(
            model_name="referralcommissionledger",
            name="commission_amount",
            field=models.DecimalField(
                decimal_places=2,
                help_text="Commission earned. Negative values are used for reversal entries.",
                max_digits=12,
            ),
        ),
        migrations.AlterField(
            model_name="referralcommissionledger",
            name="transaction",
            field=models.OneToOneField(
                blank=True,
                help_text="Original wallet transaction that generated the platform fee.",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="referral_commission",
                to="wallet.transaction",
            ),
        ),
        migrations.AlterField(
            model_name="referralcommissionledger",
            name="commission_rate",
            field=models.DecimalField(
                decimal_places=2,
                max_digits=5,
                validators=[
                    django.core.validators.MinValueValidator(0),
                    django.core.validators.MaxValueValidator(100),
                ],
            ),
        ),
        migrations.CreateModel(
            name="ReferralTransfer",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "amount",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=12,
                        validators=[
                            django.core.validators.MinValueValidator(
                                decimal.Decimal("0.01")
                            )
                        ],
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("PENDING", "Pending"),
                            ("COMPLETED", "Completed"),
                            ("FAILED", "Failed"),
                        ],
                        default="PENDING",
                        max_length=20,
                    ),
                ),
                (
                    "transfer_reference",
                    models.CharField(
                        blank=True,
                        default=None,
                        max_length=100,
                        null=True,
                        unique=True,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "commission",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="internal_transfer",
                        to="referrals.referralcommissionledger",
                    ),
                ),
                (
                    "referrer",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="commission_transfers",
                        to="referrals.referrer",
                    ),
                ),
                (
                    "wallet_transaction",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="referral_transfer",
                        to="wallet.transaction",
                    ),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
    ]
