from decimal import Decimal

import django.db.models.deletion
from django.db import migrations, models


def backfill_recognized_tournament_fees(apps, schema_editor):
    TournamentFeeSettlement = apps.get_model("matches", "TournamentFeeSettlement")
    PlatformWallet = apps.get_model("wallet", "PlatformWallet")
    PlatformTransaction = apps.get_model("wallet", "PlatformTransaction")
    database = schema_editor.connection.alias

    recognized_settlements = TournamentFeeSettlement.objects.using(database).filter(
        status="RECOGNIZED",
        platform_fee__gt=0,
    )
    if not recognized_settlements.exists():
        return

    wallet, _created = PlatformWallet.objects.using(database).get_or_create(pk=1)
    for settlement in recognized_settlements.iterator():
        PlatformTransaction.objects.using(database).get_or_create(
            fee_settlement_id=settlement.pk,
            defaults={
                "wallet_id": wallet.pk,
                "amount": settlement.platform_fee,
                "transaction_type": "TOURNAMENT_FEE",
                "description": (
                    f"PlayArena fee for tournament #{settlement.tournament_id} "
                    f"({settlement.fee_percent}%)"
                ),
            },
        )

    total = sum(
        PlatformTransaction.objects.using(database)
        .filter(wallet_id=wallet.pk)
        .values_list("amount", flat=True),
        Decimal("0.00"),
    )
    PlatformWallet.objects.using(database).filter(pk=wallet.pk).update(balance=total)


class Migration(migrations.Migration):

    dependencies = [
        ("matches", "0027_tournament_admin_fee_range"),
        ("wallet", "0017_deposit_organisation_wallet_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="PlatformWallet",
            fields=[
                (
                    "id",
                    models.PositiveSmallIntegerField(
                        default=1,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("balance", models.DecimalField(decimal_places=2, default=0, max_digits=16)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("id", 1)),
                        name="platform_wallet_singleton",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="PlatformTransaction",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("amount", models.DecimalField(decimal_places=2, max_digits=16)),
                (
                    "transaction_type",
                    models.CharField(
                        choices=[("TOURNAMENT_FEE", "Tournament Platform Fee")],
                        default="TOURNAMENT_FEE",
                        max_length=20,
                    ),
                ),
                ("description", models.CharField(max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "fee_settlement",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="platform_transaction",
                        to="matches.tournamentfeesettlement",
                    ),
                ),
                (
                    "wallet",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="transactions",
                        to="wallet.platformwallet",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.RunPython(
            backfill_recognized_tournament_fees,
            migrations.RunPython.noop,
        ),
    ]
