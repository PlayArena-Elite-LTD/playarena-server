from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('matches', '0010_remove_evidence_matches_evi_match_i_0e1b0f_idx_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='match',
            name='game',
            field=models.CharField(
                choices=[
                    ('FIFA_MOBILE', 'EA SPORTS FC 26'),
                    ('DREAM_LEAGUE_SOCCER', 'Dream League Soccer 2026'),
                    ('EFOOTBALL', 'eFootball 2026'),
                    ('LI_CHESS', 'Lichess'),
                    ('MORTAL_KOMBAT', 'Mortal Kombat 1'),
                    ('NBA_2K', 'NBA 2K'),
                    ('EIGHT_BALL_POOL', '8 Ball Pool'),
                ],
                max_length=20,
            ),
        ),
    ]
