# Hand-written: per-player result submissions (dual-submit, 1v1-style) + DISPUTED status.

from django.conf import settings
import django.db.models.deletion
from django.db import migrations, models

import matches.models


class Migration(migrations.Migration):

    dependencies = [
        ('matches', '0021_tournament_lifecycle'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name='tournamentmatch',
            name='status',
            field=models.CharField(
                choices=[
                    ('PENDING', 'Pending'),
                    ('READY', 'Ready'),
                    ('REPORTED', 'Reported'),
                    ('DISPUTED', 'Disputed'),
                    ('CONFIRMED', 'Confirmed'),
                    ('BYE', 'Bye'),
                ],
                default='PENDING',
                max_length=20,
            ),
        ),
        migrations.CreateModel(
            name='TournamentMatchSubmission',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('player1_score', models.PositiveSmallIntegerField(blank=True, null=True)),
                ('player2_score', models.PositiveSmallIntegerField(blank=True, null=True)),
                ('evidence', models.FileField(blank=True, null=True, upload_to=matches.models.tournament_evidence_path)),
                ('submitted_at', models.DateTimeField(auto_now=True)),
                ('match', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='submissions', to='matches.tournamentmatch')),
                ('player', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('winner', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['submitted_at'],
            },
        ),
        migrations.AddConstraint(
            model_name='tournamentmatchsubmission',
            constraint=models.UniqueConstraint(fields=('match', 'player'), name='unique_tournament_match_submission'),
        ),
    ]
