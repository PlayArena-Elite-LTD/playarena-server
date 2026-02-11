# Day 30 - Launch Preparation & Go-Live

Goal: Execute final launch steps, switch production settings, and monitor the system.

## 1) Final Production Checklist
- [ ] Confirm DEBUG is disabled
- [ ] Confirm ALLOWED_HOSTS/CSRF_TRUSTED_ORIGINS set
- [ ] Confirm secrets loaded from environment
- [ ] Confirm static/media storage configured
- [ ] Confirm database backups are current

## 2) Payments Go-Live
- [ ] Switch payment gateway to production keys
- [ ] Set `PAYMENT_GATEWAY_TEST_MODE=False`
- [ ] Verify production webhook endpoints
- [ ] Run a small live deposit test
- [ ] Run a small live withdrawal test

## 3) Monitoring & Alerts
- [ ] Confirm Sentry (or equivalent) is receiving errors
- [ ] Confirm uptime monitoring is active
- [ ] Confirm logs are rotating and stored

## 4) Launch Communications
- [ ] Prepare launch announcement
- [ ] Notify support team
- [ ] Update status page (if any)

## 5) Go-Live
- [ ] Enable all production features
- [ ] Monitor system health and error rate
- [ ] Monitor payment success/failure rate
- [ ] Track new signups and engagement

## 6) Post-Launch
- [ ] Review launch day incidents
- [ ] Apply hotfixes if needed
- [ ] Collect user feedback
