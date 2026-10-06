import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("referrals", "0002_internal_referral_transfers"),
        ("wallet", "0015_referral_reversal_transaction_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="referralcommissionledger",
            name="reversal_transaction",
            field=models.OneToOneField(
                blank=True,
                help_text="Normal wallet debit recording a paid commission reversal.",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="referral_commission_reversal",
                to="wallet.transaction",
            ),
        ),
    ]
