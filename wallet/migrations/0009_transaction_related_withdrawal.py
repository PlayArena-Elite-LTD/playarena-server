from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('wallet', '0008_payment_provider_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='transaction',
            name='related_withdrawal',
            field=models.ForeignKey(
                blank=True,
                help_text='Withdrawal whose reservation, completion, or refund created this entry',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='ledger_transactions',
                to='wallet.withdrawal',
            ),
        ),
        migrations.AddConstraint(
            model_name='transaction',
            constraint=models.UniqueConstraint(
                condition=models.Q(('transaction_type', 'WITHDRAWAL')),
                fields=('related_withdrawal',),
                name='unique_withdrawal_reservation_debit',
            ),
        ),
    ]
