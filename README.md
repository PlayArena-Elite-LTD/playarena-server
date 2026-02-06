# Arena2

## Pesapal (test/sandbox) setup

This project is configured to use **Pesapal** as the active deposit gateway.

### URLs you need

- **IPN endpoint (configure in Pesapal dashboard)**: `/wallet/webhooks/pesapal/`
- **Callback/redirect URL (after user pays)**: `/wallet/pesapal/callback/`

### Quick start (PowerShell)

Preferred: put your keys in `local.env` (gitignored) and run the server.

See `local.env.example` → copy to `local.env` and fill values.

Then create a deposit with payment method **Pesapal** and you’ll be redirected to the Pesapal checkout URL.

Notes:
- Pesapal typically requires an **IPN notification_id** (`PESAPAL_IPN_ID`). If you don’t set it, the app will **attempt to auto-register IPN**
  using your `/wallet/webhooks/pesapal/` URL (this only works if your server is publicly reachable).

If you're developing locally, use a tunnel (ngrok / Cloudflare Tunnel) and set:
- `PUBLIC_BASE_URL=https://<your-public-domain>` (so the app generates public callback/IPN URLs)