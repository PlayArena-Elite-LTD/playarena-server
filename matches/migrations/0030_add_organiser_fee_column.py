from django.db import migrations


class Migration(migrations.Migration):
    """Intentionally empty.

    This migration originally re-added the organiser fee columns that
    0028_tournament_organiser_earnings already creates, which crashed deploys
    with DuplicateColumn. 0028 now adds them only when they are missing, so
    nothing is needed here. Kept so the migration graph stays stable.
    """

    dependencies = [
        ('matches', '0029_tournament_payout_withholding'),
    ]

    operations = []
