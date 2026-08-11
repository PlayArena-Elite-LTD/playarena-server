# Hand-written: adds the TOURNAMENT_WINNINGS transaction type.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('wallet', '0011_transaction_related_tournament'),
    ]

    operations = [
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
                    ('TOURNAMENT_WINNINGS', 'Tournament Winnings'),
                    ('OTHER', 'Other'),
                ],
                max_length=20,
            ),
        ),
    ]
