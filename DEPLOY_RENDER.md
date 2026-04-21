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
- `PAYMENT_GATEWAY_TEST_MODE=true`
- `BANK_PAYOUT_MODE=mock`
- Set `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, `DJANGO_CORS_ALLOWED_ORIGINS`
- `DATABASE_URL` is auto-wired from the managed Render Postgres service

## 4) Switch to real bank endpoints

When ready to go live:

1. In Render environment variables:
   - `BANK_PAYOUT_MODE=live`
   - `BANK_PAYOUT_API_URL=https://your-real-bank-api.example/payouts`
   - `BANK_PAYOUT_API_KEY=<real-secret>`
2. Set `PAYMENT_GATEWAY_TEST_MODE=false` for real provider behavior.
3. Re-deploy and verify with a small controlled test transaction first.

## Notes

- `DATABASE_URL` takes precedence over `DB_ENGINE/DB_*`.
- API routes are mounted at `/api/`.
- On Linux (Render), `python-magic` is used; on Windows, `python-magic-bin` is used.
