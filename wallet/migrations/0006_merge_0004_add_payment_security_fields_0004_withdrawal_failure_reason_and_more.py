# Generated manually to merge conflicting migrations

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('wallet', '0004_add_payment_security_fields'),
        ('wallet', '0004_withdrawal_failure_reason_and_more'),
    ]

    operations = [
        # This is a merge migration - no operations needed
        # Both parent migrations have already been applied
    ]
