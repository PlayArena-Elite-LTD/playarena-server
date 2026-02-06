from django.conf import settings
from django.core.management.base import BaseCommand


def _mask(value: str) -> str:
    if not value:
        return "(not set)"
    v = str(value)
    tail = v[-4:] if len(v) >= 4 else v
    return f"set (len={len(v)}, last4={tail})"


class Command(BaseCommand):
    help = "Print whether Pesapal settings are configured (without exposing secrets)."

    def handle(self, *args, **options):
        key = (getattr(settings, "PESAPAL_CONSUMER_KEY", "") or "").strip()
        secret = (getattr(settings, "PESAPAL_CONSUMER_SECRET", "") or "").strip()
        base_url = (getattr(settings, "PESAPAL_BASE_URL", "") or "").strip()
        ipn_id = (getattr(settings, "PESAPAL_IPN_ID", "") or "").strip()

        self.stdout.write("Pesapal configuration:")
        self.stdout.write(f"- PESAPAL_CONSUMER_KEY:    {_mask(key)}")
        self.stdout.write(f"- PESAPAL_CONSUMER_SECRET: {_mask(secret)}")
        self.stdout.write(f"- PESAPAL_BASE_URL:        {base_url or '(not set)'}")
        self.stdout.write(f"- PESAPAL_IPN_ID:          {ipn_id or '(not set)'}")

