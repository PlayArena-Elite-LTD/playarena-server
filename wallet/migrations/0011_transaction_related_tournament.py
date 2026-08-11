# Hand-written: adds related_tournament FK and tournament transaction types.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('wallet', '0010_paymentgatewaysetting_zynle'),
        ('matches', '0014_tournament'),
    ]

    operations = [
        migrations.AddField(
            model_name='transaction',
            name='related_tournament',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to='matches.tournament',
            ),
        ),
        migrations.AlterField(
            model_name='transaction',
            name='transaction_type',
            field=models.CharField(
                choices=[
                    ('DEPOSIT', 'Deposit'),
                    ('WITHDRAWAL', 'Withdrawal'),
                    ('MATCH_CREATION', 'Match Creation'),
                    ('MATCH_JOINING', 'Match Joining'),
                    ('MATCH_WINNINGS', 'Match Winnings'),
                    ('MATCH_REFUND', 'Match Refund'),
                    ('MATCH_DRAW_RETURN', 'Match Draw Return'),
                    ('TOURNAMENT_JOINING', 'Tournament Joining'),
                    ('TOURNAMENT_REFUND', 'Tournament Refund'),
                    ('OTHER', 'Other'),
                ],
                max_length=20,
            ),
        ),
    ]
