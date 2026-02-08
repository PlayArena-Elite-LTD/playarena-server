import json

from django.core.management.base import BaseCommand, CommandError

from wallet.pesapal_service import get_pesapal_client


class Command(BaseCommand):
    help = "Register the Pesapal IPN URL and print the resulting notification_id (PESAPAL_IPN_ID)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--url",
            required=True,
            help="Publicly reachable IPN URL (example: https://yourdomain.com/wallet/webhooks/pesapal/)",
        )
        parser.add_argument(
            "--type",
            default="GET",
            help="IPN notification type (commonly GET).",
        )

    def handle(self, *args, **options):
        ipn_url = options["url"]
        notification_type = options["type"]

        client = get_pesapal_client()
        try:
            resp = client.register_ipn(ipn_url=ipn_url, notification_type=notification_type)
        except Exception as e:
            raise CommandError(str(e))

        self.stdout.write(json.dumps(resp, indent=2))
        data = resp.get("data", resp) if isinstance(resp, dict) else {}
        ipn_id = data.get("ipn_id") or data.get("ipnId") or data.get("notification_id") or data.get("id")
        if ipn_id:
            self.stdout.write(self.style.SUCCESS(f"\nSet PESAPAL_IPN_ID={ipn_id}\n"))
