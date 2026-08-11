# Hand-written: adds per-entry fee/prize-pool split and configurable prize positions.

from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


def backfill_fee_split(apps, schema_editor):
    """Populate platform_fee / prize_contribution for existing registrations."""
    TournamentRegistration = apps.get_model('matches', 'TournamentRegistration')
    percent = Decimal(str(getattr(settings, 'TOURNAMENT_PLATFORM_FEE_PERCENT', 10)))
    for reg in TournamentRegistration.objects.all().iterator():
        amount = Decimal(reg.amount_paid)
        fee = (amount * percent / Decimal('100')).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )
        reg.platform_fee = fee
        reg.prize_contribution = amount - fee
        reg.save(update_fields=['platform_fee', 'prize_contribution'])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('matches', '0016_tournamentregistration'),
    ]

    operations = [
        migrations.AddField(
            model_name='tournamentregistration',
            name='platform_fee',
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal('0.00'),
                help_text='PlayArena platform fee taken from this entry.',
                max_digits=10,
            ),
        ),
        migrations.AddField(
            model_name='tournamentregistration',
            name='prize_contribution',
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal('0.00'),
                help_text='Portion of this entry added to the tournament prize pool.',
                max_digits=10,
            ),
        ),
        migrations.CreateModel(
            name='TournamentPrize',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('position', models.PositiveIntegerField(help_text='Finishing position: 1 = 1st place, 2 = 2nd place, ...', validators=[django.core.validators.MinValueValidator(1)])),
                ('percentage', models.DecimalField(decimal_places=2, help_text='Share of the prize pool awarded to this position.', max_digits=5, validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(100)])),
                ('tournament', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='prizes', to='matches.tournament')),
            ],
            options={
                'ordering': ['position'],
            },
        ),
        migrations.AddConstraint(
            model_name='tournamentprize',
            constraint=models.UniqueConstraint(fields=('tournament', 'position'), name='unique_tournament_prize_position'),
        ),
        migrations.RunPython(backfill_fee_split, noop_reverse),
    ]
