# Hand-written: capture the player's team name and WhatsApp/phone number per
# tournament registration (standardised player metadata).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('matches', '0022_tournament_match_submissions'),
    ]

    operations = [
        migrations.AddField(
            model_name='tournamentregistration',
            name='team_name',
            field=models.CharField(
                max_length=120,
                blank=True,
                default='',
                help_text="Team the player represents in this tournament (e.g. 'Power Dynamos').",
            ),
        ),
        migrations.AddField(
            model_name='tournamentregistration',
            name='phone',
            field=models.CharField(
                max_length=32,
                blank=True,
                default='',
                help_text="WhatsApp / phone number for the player, stored with the +260 country code where applicable.",
            ),
        ),
    ]
