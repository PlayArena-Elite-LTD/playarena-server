# Hand-written: adds single-elimination bracket matches for tournaments.

from django.conf import settings
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('matches', '0018_tournament_standings_and_payouts'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='TournamentMatch',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('round_number', models.PositiveIntegerField()),
                ('slot_number', models.PositiveIntegerField()),
                ('next_slot', models.PositiveSmallIntegerField(blank=True, null=True)),
                ('status', models.CharField(choices=[('PENDING', 'Pending'), ('READY', 'Ready'), ('REPORTED', 'Reported'), ('CONFIRMED', 'Confirmed'), ('BYE', 'Bye')], default='PENDING', max_length=20)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('tournament', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='bracket_matches', to='matches.tournament')),
                ('player1', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('player2', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('winner', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('reported_winner', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('reported_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('next_match', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='matches.tournamentmatch')),
            ],
            options={
                'ordering': ['round_number', 'slot_number'],
            },
        ),
        migrations.AddConstraint(
            model_name='tournamentmatch',
            constraint=models.UniqueConstraint(fields=('tournament', 'round_number', 'slot_number'), name='unique_tournament_match_slot'),
        ),
    ]
