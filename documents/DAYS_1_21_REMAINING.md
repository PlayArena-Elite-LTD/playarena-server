# Days 1-21 Remaining Items (Observed)

This list is based on a quick scan of the current codebase and the 30-day plan.

## Day 1 - Project Setup & Database Migration
- PostgreSQL setup + production config
- `psycopg2-binary` dependency
- `.env` file + environment variable loading (`django-environ` or `python-decouple`)
- Move hardcoded secrets from `settings.py`

## Day 2 - Security Hardening
- CAPTCHA on registration/login forms (dependency installed, not wired)
- Password strength indicator UI
- Enforce CSP via middleware/package (settings exist, headers not enforced)

## Day 4 - Wallet UI Implementation
- JavaScript validation / payment client flow on wallet forms

## Days 5-6 - Payment Gateway Integration
- Stripe/PayPal SDK wiring if required
- Stripe/PayPal withdrawals (currently stubbed)
- End-to-end payment flow tests

## Day 8 - Evidence Upload UI
- Upload progress bar
- Drag-and-drop upload (optional)

## Day 11 - Logging & Monitoring
- Monitoring dashboard (Grafana or similar)
- Log rotation strategy beyond Django logging config

## Day 12 - Additional Games & Devices
- Landing page visuals/icons for the new games/devices (needs verification)

## Days 15-21 - API Layer & Security
- API versioning (`/api/v1/` or DRF versioning config)
- API caching
- Performance optimization pass (query tuning / N+1 review)
- Extra request/response validation beyond serializers
