# Hand-written: make PlayArena's administration/revenue percentage configurable
# per tournament instead of a fixed platform-wide value. Existing tournaments
# were all created under the 10% regime, so they are backfilled with 10.00.

from decimal import Decimal

import django.core.validators
from django.db import migrations, models

import matches.models


class Migration(migrations.Migration):

    dependencies = [
        ('matches', '0023_registration_team_and_phone'),
    ]

    operations = [
        migrations.AddField(
            model_name='tournament',
            name='platform_fee_percent',
            field=models.DecimalField(
                max_digits=5,
                decimal_places=2,
                default=Decimal('10.00'),
                validators=[
                    django.core.validators.MinValueValidator(0),
                    django.core.validators.MaxValueValidator(100),
                ],
                help_text='PlayArena administration / revenue percentage taken from each entry (configurable per tournament).',
            ),
        ),
        migrations.AlterField(
            model_name='tournament',
            name='platform_fee_percent',
            field=models.DecimalField(
                max_digits=5,
                decimal_places=2,
                default=matches.models._default_platform_fee_percent,
                validators=[
                    django.core.validators.MinValueValidator(0),
                    django.core.validators.MaxValueValidator(100),
                ],
                help_text='PlayArena administration / revenue percentage taken from each entry (configurable per tournament).',
            ),
        ),
    ]
