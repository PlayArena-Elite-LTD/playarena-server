# Hand-written: adds final standings and automatic payout records for tournaments.

from django.conf import settings
import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('matches', '0017_tournament_fees_and_prizes'),
        ('wallet', '0012_transaction_tournament_winnings'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='TournamentStanding',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('position', models.PositiveIntegerField(help_text='Final rank: 1 = winner, 2 = runner-up, ...', validators=[django.core.validators.MinValueValidator(1)])),
                ('points', models.DecimalField(blank=True, decimal_places=2, help_text='Optional score/points for display (game-specific).', max_digits=10, null=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('player', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='tournament_standings', to=settings.AUTH_USER_MODEL)),
                ('tournament', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='standings', to='matches.tournament')),
            ],
            options={
                'ordering': ['position'],
            },
        ),
        migrations.CreateModel(
            name='TournamentPayout',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('position', models.PositiveIntegerField(validators=[django.core.validators.MinValueValidator(1)])),
                ('amount', models.DecimalField(decimal_places=2, max_digits=10)),
                ('status', models.CharField(choices=[('PENDING', 'Pending'), ('PAID', 'Paid'), ('FAILED', 'Failed')], default='PENDING', max_length=20)),
                ('failure_reason', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('paid_at', models.DateTimeField(blank=True, null=True)),
                ('player', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='tournament_payouts', to=settings.AUTH_USER_MODEL)),
                ('tournament', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='payouts', to='matches.tournament')),
                ('transaction', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='tournament_payouts', to='wallet.transaction')),
            ],
            options={
                'ordering': ['position'],
            },
        ),
        migrations.AddConstraint(
            model_name='tournamentstanding',
            constraint=models.UniqueConstraint(fields=('tournament', 'player'), name='unique_tournament_standing_player'),
        ),
        migrations.AddConstraint(
            model_name='tournamentstanding',
            constraint=models.UniqueConstraint(fields=('tournament', 'position'), name='unique_tournament_standing_position'),
        ),
        migrations.AddConstraint(
            model_name='tournamentpayout',
            constraint=models.UniqueConstraint(fields=('tournament', 'position'), name='unique_tournament_payout_position'),
        ),
    ]
