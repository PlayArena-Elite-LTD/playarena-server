import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("matches", "0029_tournament_payout_withholding"),
        ("wallet", "0019_organisation_tournament_earnings"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="organisationtransaction",
            name="fee_settlement",
        ),
        migrations.AddField(
            model_name="organisationtransaction",
            name="tournament_payout",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="organiser_transaction",
                to="matches.tournamentpayout",
            ),
        ),
    ]
