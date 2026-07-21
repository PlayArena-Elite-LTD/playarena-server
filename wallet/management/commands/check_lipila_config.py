from django.core.management.base import BaseCommand
from django.conf import settings


def _mask(value: str) -> str:
    value = (value or '').strip()
    if not value:
        return '(not set)'
    if len(value) <= 8:
        return '***'
    return f'{value[:4]}...{value[-4:]}'


class Command(BaseCommand):
    help = 'Print Lipila / payment configuration status (masked).'

    def handle(self, *args, **options):
        secret = (getattr(settings, 'LIPILA_SECRET_KEY', '') or '').strip()
        base_url = (getattr(settings, 'LIPILA_BASE_URL', '') or '').strip()
        disbursement_base_url = (getattr(settings, 'LIPILA_DISBURSEMENT_BASE_URL', '') or '').strip()
        disbursement_path = (getattr(settings, 'LIPILA_MOBILE_MONEY_DISBURSEMENT_PATH', '') or '').strip()
        currency = (getattr(settings, 'LIPILA_CURRENCY', '') or '').strip()
        mock_mode = bool(getattr(settings, 'LIPILA_MOCK_MODE', False))
        public_base = (getattr(settings, 'PUBLIC_BASE_URL', '') or '').strip()
        webhook_url = (getattr(settings, 'LIPILA_WEBHOOK_URL', '') or '').strip()
        provider = (getattr(settings, 'PAYMENT_PROVIDER', '') or '').strip()

        self.stdout.write('Payment configuration:')
        self.stdout.write(f'- PAYMENT_PROVIDER:   {provider or "(not set)"}')
        self.stdout.write(f'- LIPILA_SECRET_KEY:  {_mask(secret)}')
        self.stdout.write(f'- LIPILA_BASE_URL:    {base_url or "(not set)"}')
        self.stdout.write(f'- DISBURSE_BASE_URL:  {disbursement_base_url or "(uses LIPILA_BASE_URL)"}')
        self.stdout.write(f'- DISBURSE_PATH:      {disbursement_path or "(not set)"}')
        self.stdout.write(f'- LIPILA_CURRENCY:    {currency or "(not set)"}')
        self.stdout.write(f'- LIPILA_MOCK_MODE:   {mock_mode}')
        self.stdout.write(f'- LIPILA_WEBHOOK_URL: {webhook_url or "(auto from PUBLIC_BASE_URL)"}')
        self.stdout.write(f'- PUBLIC_BASE_URL:    {public_base or "(not set)"}')

        if mock_mode:
            self.stdout.write(self.style.SUCCESS('Mock mode is ON — use webhook or status poll to confirm.'))
        elif secret:
            self.stdout.write(self.style.SUCCESS('Lipila secret key is set — ready for sandbox/live calls.'))
        else:
            self.stdout.write(self.style.WARNING('No secret key and mock mode is OFF — Lipila deposits will fail.'))
