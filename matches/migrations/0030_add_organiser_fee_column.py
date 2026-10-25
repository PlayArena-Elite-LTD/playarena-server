from decimal import Decimal

from django.db import migrations, models
from django.core.validators import MinValueValidator, MaxValueValidator


class Migration(migrations.Migration):

    dependencies = [
        ('matches', '0029_tournament_payout_withholding'),
    ]

    operations = [
        migrations.AddField(
            model_name='tournament',
            name='organiser_fee_percent',
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal('10.00'),
                help_text='Organiser share percentage of the pool remaining after the platform fee.',
                max_digits=5,
                validators=[
                    MinValueValidator(0),
                    MaxValueValidator(10),
                ],
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='tournamentfeesettlement',
            name='organiser_fee',
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal('0.00'),
                max_digits=16,
            ),
        ),
        migrations.AddField(
            model_name='tournamentfeesettlement',
            name='organiser_fee_percent',
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal('10.00'),
                max_digits=5,
            ),
        ),
        migrations.AddField(
            model_name='tournamentregistration',
            name='organiser_fee',
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal('0.00'),
                help_text='Organiser earnings allocated from this entry.',
                max_digits=10,
            ),
        ),
    ]
