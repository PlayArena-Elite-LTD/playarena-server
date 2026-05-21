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
    help = 'Print Lipila configuration status (masked).'

    def handle(self, *args, **options):
        api_key = (getattr(settings, 'LIPILA_API_KEY', '') or '').strip()
        base_url = (getattr(settings, 'LIPILA_BASE_URL', '') or '').strip()
        currency = (getattr(settings, 'LIPILA_CURRENCY', '') or '').strip()
        mock_mode = bool(getattr(settings, 'LIPILA_MOCK_MODE', False))
        public_base = (getattr(settings, 'PUBLIC_BASE_URL', '') or '').strip()

        self.stdout.write('Lipila configuration:')
        self.stdout.write(f'- LIPILA_API_KEY:     {_mask(api_key)}')
        self.stdout.write(f'- LIPILA_BASE_URL:    {base_url or "(not set)"}')
        self.stdout.write(f'- LIPILA_CURRENCY:    {currency or "(not set)"}')
        self.stdout.write(f'- LIPILA_MOCK_MODE:   {mock_mode}')
        self.stdout.write(f'- PUBLIC_BASE_URL:    {public_base or "(not set)"}')

        if mock_mode:
            self.stdout.write(self.style.SUCCESS('Mock mode is ON — deposits complete without calling Lipila.'))
        elif api_key:
            self.stdout.write(self.style.SUCCESS('Lipila API key is set — ready for sandbox/live calls.'))
        else:
            self.stdout.write(self.style.WARNING('No API key and mock mode is OFF — Lipila deposits will fail.'))
