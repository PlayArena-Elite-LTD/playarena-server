import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("matches", "0028_tournament_organiser_earnings"),
        ("wallet", "0018_platform_tournament_fee_wallet"),
    ]

    operations = [
        migrations.AlterField(
            model_name="organisationwallet",
            name="balance",
            field=models.DecimalField(decimal_places=2, default=0.0, max_digits=16),
        ),
        migrations.AlterField(
            model_name="organisationtransaction",
            name="amount",
            field=models.DecimalField(decimal_places=2, max_digits=16),
        ),
        migrations.AlterField(
            model_name="organisationtransaction",
            name="transaction_type",
            field=models.CharField(
                choices=[
                    ("DEPOSIT", "Deposit"),
                    ("WITHDRAWAL", "Withdrawal"),
                    ("MATCH_CREATION", "Match Creation"),
                    ("MATCH_JOINING", "Match Joining"),
                    ("MATCH_WINNINGS", "Match Winnings"),
                    ("MATCH_REFUND", "Match Refund"),
                    ("MATCH_DRAW_RETURN", "Match Draw Return"),
                    ("TOURNAMENT_JOINING", "Tournament Joining"),
                    ("TOURNAMENT_REFUND", "Tournament Refund"),
                    ("TOURNAMENT_WINNINGS", "Tournament Winnings"),
                    ("TOURNAMENT_EARNINGS", "Tournament Organiser Earnings"),
                    ("REFERRAL_TRANSFER", "Referral Commission Transfer"),
                    ("REFERRAL_REVERSAL", "Referral Commission Reversal"),
                    ("OTHER", "Other"),
                ],
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="organisationtransaction",
            name="fee_settlement",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="organiser_transaction",
                to="matches.tournamentfeesettlement",
            ),
        ),
    ]
