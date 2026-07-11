from django.db import migrations, models


def create_default_setting(apps, schema_editor):
    setting = apps.get_model('wallet', 'PaymentGatewaySetting')
    setting.objects.get_or_create(pk=1, defaults={'active_provider': 'lipila'})


class Migration(migrations.Migration):
    dependencies = [('wallet', '0009_transaction_related_withdrawal')]

    operations = [
        migrations.CreateModel(
            name='PaymentGatewaySetting',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('active_provider', models.CharField(
                    choices=[('lipila', 'Lipila'), ('zynle', 'ZynlePay')],
                    default='lipila',
                    help_text='New deposits use this gateway. Existing deposits keep their original gateway.',
                    max_length=20,
                )),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Payment gateway setting',
                'verbose_name_plural': 'Payment gateway settings',
            },
        ),
        migrations.AlterField(
            model_name='deposit',
            name='payment_method',
            field=models.CharField(choices=[
                ('LIPILA', 'Lipila (Card)'),
                ('LIPILA_MOMO', 'Lipila (Mobile Money)'),
                ('ZYNLE_MOMO', 'ZynlePay (Mobile Money)'),
                ('PESAPAL', 'Pesapal (legacy)'),
                ('ZYNELPAY', 'Zynel Pay (legacy)'),
                ('PAYPAL', 'PayPal (legacy)'),
                ('STRIPE', 'Stripe (legacy)'),
                ('MOBILE_MONEY', 'Mobile Money (legacy)'),
                ('BANK_TRANSFER', 'Bank Transfer'),
                ('OTHER', 'Other'),
            ], max_length=20),
        ),
        migrations.AlterField(
            model_name='deposit',
            name='payment_provider',
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text='Gateway slug used for this deposit (e.g. lipila or zynle)',
                max_length=32,
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name='deposit',
            name='provider_transaction_id',
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text='Provider transaction identifier',
                max_length=255,
                null=True,
            ),
        ),
        migrations.RunPython(create_default_setting, migrations.RunPython.noop),
    ]
