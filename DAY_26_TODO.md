# Day 26 - Production Deployment Setup

Goal: Prepare production infrastructure, environment, and security hardening for launch.

## 1) Infrastructure & Server
- [ ] Provision production server (AWS/GCP/Azure/PAAS)
- [ ] Configure OS updates and security patches
- [ ] Create non-root deploy user with SSH keys
- [ ] Configure firewall (allow only required ports)
- [ ] Set up reverse proxy (Nginx/Caddy)

## 2) Database (PostgreSQL)
- [ ] Provision production PostgreSQL instance
- [ ] Create database user with least privilege
- [ ] Configure database backups
- [ ] Set connection pooling (if needed)
- [ ] Apply connection limits and SSL settings

## 3) Environment Variables & Secrets
- [ ] Create `.env` or secret manager entries
- [ ] Move all hardcoded secrets into env
- [ ] Set `DEBUG=False`
- [ ] Set `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`
- [ ] Configure email credentials securely

## 4) Static & Media Storage
- [ ] Configure `STATIC_ROOT` and collectstatic
- [ ] Configure media storage (S3/Cloudinary/local)
- [ ] Ensure media permissions are restricted
- [ ] Enable CDN for static assets (optional)

## 5) Security Hardening
- [ ] Enforce HTTPS and redirect HTTP → HTTPS
- [ ] Enable HSTS for HTTPS
- [ ] Configure secure cookies in production
- [ ] Confirm CSP headers enforced
- [ ] Ensure admin URLs restricted to staff

## 6) Logging & Monitoring
- [ ] Configure production logging output paths
- [ ] Set log rotation policy
- [ ] Enable error reporting (Sentry or similar)
- [ ] Configure uptime monitoring (optional)

## 7) Payments & Webhooks
- [ ] Configure production gateway keys
- [ ] Update webhook URLs to production
- [ ] Verify webhook signature secrets are set
- [ ] Set `PAYMENT_GATEWAY_TEST_MODE=False`

## 8) Background Tasks (if used)
- [ ] Configure cron/scheduler jobs (reconciliation)
- [ ] Verify scheduled jobs run as expected

## 9) Pre-Deployment Checklist
- [ ] Run tests in staging environment
- [ ] Verify database migrations are clean
- [ ] Check admin access in production
- [ ] Confirm backups and rollback plan
