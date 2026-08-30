# Hand-written: leagues can be played home-and-away (double round-robin) so each
# matchup is played twice. Defaults to True to match the two-fixture league spec;
# knockouts ignore it (always single-leg).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('matches', '0024_tournament_platform_fee_percent'),
    ]

    operations = [
        migrations.AddField(
            model_name='tournament',
            name='home_and_away',
            field=models.BooleanField(
                default=True,
                help_text='Leagues only: play each matchup twice (home and away). Knockouts are always single-leg.',
            ),
        ),
    ]
