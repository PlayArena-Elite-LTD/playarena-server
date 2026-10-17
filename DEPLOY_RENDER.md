# Render Deployment And Payment Testing

## 1) Local setup (mock mode)

1. Copy `local.env.example` to `local.env`.
2. Keep:
   - `PAYMENT_GATEWAY_TEST_MODE=true`
   - `BANK_PAYOUT_MODE=mock`
3. Run locally:
   - `python manage.py migrate`
   - `python manage.py runserver`

In this mode:
- Pesapal can run in mock mode (`PESAPAL_MOCK_MODE=true`).
- Bank withdrawals do not call an external API and return mock/pending responses.

## 2) Local setup (mock bank API endpoint)

If you want to test real HTTP integration but still with a fake backend:

1. Start your mock payout API (local or container).
2. Set:
   - `BANK_PAYOUT_MODE=live`
   - `BANK_PAYOUT_API_URL=http://127.0.0.1:9000/payouts` (example)
   - `BANK_PAYOUT_API_KEY=your-mock-key` (if required by your mock server)
3. Trigger a withdrawal and verify your mock API receives requests.

## 3) Render deployment (safe first deploy)

The repository includes:
- `render.yaml`
- `Procfile`
- `runtime.txt`

`render.yaml` provisions a managed PostgreSQL database (`playyarena-db`) and injects
its connection string into the web service as `DATABASE_URL`.
This means all `migrate` operations on Render run against Postgres by default.

Recommended first deployment values:
- `DEBUG=false`
- `PAYMENT_GATEWAY_TEST_MODE=false`
- `LIPILA_MOCK_MODE=false`
- `BANK_PAYOUT_MODE=mock`
- `DJANGO_ALLOWED_HOSTS=<your-render-service>.onrender.com`
- `DJANGO_CSRF_TRUSTED_ORIGINS=https://<your-render-service>.onrender.com`
- `DJANGO_CORS_ALLOWED_ORIGINS=https://www.playarenaelite.com,https://playarenaelite.com`
- `FRONTEND_URL=https://www.playarenaelite.com`
- `DATABASE_URL` is auto-wired from the managed Render Postgres service

Your Vercel frontend must call the Render backend URL, not localhost. Set the
frontend API base URL environment variable in Vercel:

- `NEXT_PUBLIC_API_BASE_URL=https://<your-render-service>.onrender.com`

Use the backend origin only: the frontend already appends `/api/...` to this
value. Do not add `/api` to the environment variable, or requests will target
`/api/api/...`.

After changing a Vercel build-time environment variable, redeploy the frontend.

Render's `startCommand` runs `python manage.py migrate` before starting Gunicorn,
so pending migrations (including organisation wallet migrations) are applied to
the Render Postgres database on deployment. Confirm the deployment logs show
migrations completing successfully.

### Payment callbacks and credentials

- Set `LIPILA_SECRET_KEY` in Render to the credential for the selected Lipila
   environment. Keep mock mode disabled only when this credential and the
   provider account are ready.
- If using Lipila webhook signing, set `LIPILA_WEBHOOK_SECRET` in Render to the
   signing secret from the provider. Register
   `https://<your-render-service>.onrender.com/api/payments/lipila/webhook/` as
   the provider's webhook URL.
- If using ZynlePay, set `ZYNLE_API_KEY`, `ZYNLE_API_ID`, and
   `ZYNLE_MERCHANT_ID`. Set the Zynle callback URL to
   `https://<your-render-service>.onrender.com/api/payments/zynle/webhook/?token=<ZYNLE_CALLBACK_TOKEN>`;
   copy the generated token from Render's environment settings into the Zynle
   dashboard. Never commit provider credentials or callback tokens.
- The Render template keeps `BANK_PAYOUT_MODE=mock`. Do not enable live bank
   payouts until a real payout endpoint and API key have been configured and
   tested separately.

These credentials and provider-dashboard callback registrations must be
configured in Render/Vercel and the provider dashboard; they cannot be verified
from a local checkout.

## 4) Switch to real bank endpoints

When ready to go live:

1. In Render environment variables:
   - `BANK_PAYOUT_MODE=live`
   - `BANK_PAYOUT_API_URL=https://your-real-bank-api.example/payouts`
   - `BANK_PAYOUT_API_KEY=<real-secret>`
2. Keep `PAYMENT_GATEWAY_TEST_MODE=false` and `LIPILA_MOCK_MODE=false` for real provider behavior.
3. Re-deploy and verify with a small controlled test transaction first.

## Notes

- `DATABASE_URL` takes precedence over `DB_ENGINE/DB_*`.
- API routes are mounted at `/api/`.
- On Linux (Render), `python-magic` is used; on Windows, `python-magic-bin` is used.
