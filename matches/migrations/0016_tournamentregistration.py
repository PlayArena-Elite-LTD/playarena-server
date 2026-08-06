# Hand-written: adds TournamentRegistration for the tournament join/leave flow.

from django.conf import settings
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('matches', '0015_tournament_default_open'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='TournamentRegistration',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('REGISTERED', 'Registered'), ('WITHDRAWN', 'Withdrawn')], default='REGISTERED', max_length=20)),
                ('amount_paid', models.DecimalField(decimal_places=2, max_digits=10)),
                ('joined_at', models.DateTimeField(auto_now_add=True)),
                ('left_at', models.DateTimeField(blank=True, null=True)),
                ('player', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='tournament_registrations', to=settings.AUTH_USER_MODEL)),
                ('tournament', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='registrations', to='matches.tournament')),
            ],
            options={
                'ordering': ['-joined_at'],
            },
        ),
        migrations.AddConstraint(
            model_name='tournamentregistration',
            constraint=models.UniqueConstraint(fields=('tournament', 'player'), name='unique_tournament_player_registration'),
        ),
    ]
