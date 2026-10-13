from decimal import Decimal

import django.core.validators
from django.db import migrations, models

import matches.models


class Migration(migrations.Migration):

    dependencies = [
        ('matches', '0026_tournament_full_capacity_fee_settlement'),
    ]

    operations = [
        migrations.AlterField(
            model_name='tournament',
            name='platform_fee_percent',
            field=models.DecimalField(
                decimal_places=2,
                default=matches.models._default_platform_fee_percent,
                help_text='PlayArena administration fee percentage (organiser-configurable from 0% to 10%).',
                max_digits=5,
                validators=[
                    django.core.validators.MinValueValidator(0),
                    django.core.validators.MaxValueValidator(10),
                ],
            ),
        ),
        migrations.AlterField(
            model_name='tournamentregistration',
            name='platform_fee',
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal('0.00'),
                help_text='PlayArena administration fee allocated from this entry.',
                max_digits=10,
            ),
        ),
    ]
