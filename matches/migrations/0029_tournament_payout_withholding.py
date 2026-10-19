from decimal import Decimal

from django.db import migrations, models


def restore_post_platform_pools(apps, schema_editor):
    TournamentFeeSettlement = apps.get_model("matches", "TournamentFeeSettlement")
    TournamentRegistration = apps.get_model("matches", "TournamentRegistration")
    database = schema_editor.connection.alias

    for settlement in TournamentFeeSettlement.objects.using(database).iterator():
        settlement.net_prize_pool = settlement.gross_pool - settlement.platform_fee
        settlement.save(using=database, update_fields=["net_prize_pool"])

    registrations = TournamentRegistration.objects.using(database).filter(
        status="REGISTERED"
    )
    for registration in registrations.iterator():
        registration.organiser_fee = Decimal("0.00")
        registration.prize_contribution = (
            registration.amount_paid - registration.platform_fee
        )
        registration.save(
            using=database,
            update_fields=["organiser_fee", "prize_contribution"],
        )


def populate_gross_payouts(apps, schema_editor):
    TournamentPayout = apps.get_model("matches", "TournamentPayout")
    database = schema_editor.connection.alias
    TournamentPayout.objects.using(database).all().update(
        gross_amount=models.F("amount"),
        organiser_fee=Decimal("0.00"),
    )


class Migration(migrations.Migration):

    dependencies = [
        ("matches", "0028_tournament_organiser_earnings"),
    ]

    operations = [
        migrations.AddField(
            model_name="tournamentpayout",
            name="gross_amount",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                max_digits=16,
            ),
        ),
        migrations.AddField(
            model_name="tournamentpayout",
            name="organiser_fee",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                max_digits=16,
            ),
        ),
        migrations.AlterField(
            model_name="tournamentpayout",
            name="amount",
            field=models.DecimalField(decimal_places=2, max_digits=16),
        ),
        migrations.RunPython(populate_gross_payouts, migrations.RunPython.noop),
        migrations.RunPython(restore_post_platform_pools, migrations.RunPython.noop),
    ]
