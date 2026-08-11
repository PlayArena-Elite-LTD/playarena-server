# Hand-written: expands tournament lifecycle statuses and adds registration windows.

from django.db import migrations, models


def in_progress_to_live(apps, schema_editor):
    Tournament = apps.get_model('matches', 'Tournament')
    Tournament.objects.filter(status='IN_PROGRESS').update(status='LIVE')


def live_to_in_progress(apps, schema_editor):
    Tournament = apps.get_model('matches', 'Tournament')
    Tournament.objects.filter(status='LIVE').update(status='IN_PROGRESS')


class Migration(migrations.Migration):

    dependencies = [
        ('matches', '0020_tournament_format_and_match_scores'),
    ]

    operations = [
        migrations.AddField(
            model_name='tournament',
            name='registration_opens_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='tournament',
            name='registration_closes_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='tournament',
            name='status',
            field=models.CharField(
                choices=[
                    ('DRAFT', 'Draft'),
                    ('OPEN', 'Registration Open'),
                    ('REG_CLOSED', 'Registration Closed'),
                    ('SCHEDULED', 'Scheduled'),
                    ('LIVE', 'Live'),
                    ('RESULTS_PENDING', 'Results Pending'),
                    ('COMPLETED', 'Completed'),
                    ('PAYOUT_PROCESSING', 'Payout Processing'),
                    ('PAID', 'Paid / Settled'),
                    ('CANCELLED', 'Cancelled'),
                ],
                default='OPEN',
                max_length=20,
            ),
        ),
        migrations.RunPython(in_progress_to_live, live_to_in_progress),
    ]
