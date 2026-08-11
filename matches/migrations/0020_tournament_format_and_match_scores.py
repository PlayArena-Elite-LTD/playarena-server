# Hand-written: adds tournament format and per-fixture scorelines for leagues.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('matches', '0019_tournamentmatch'),
    ]

    operations = [
        migrations.AddField(
            model_name='tournament',
            name='format',
            field=models.CharField(
                choices=[('KNOCKOUT', 'Knockout / Cup'), ('LEAGUE', '7-Day League')],
                default='KNOCKOUT',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='tournamentmatch',
            name='player1_score',
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='tournamentmatch',
            name='player2_score',
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
    ]
