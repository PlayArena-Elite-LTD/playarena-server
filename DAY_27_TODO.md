# Day 27 - Deployment & Migration

Goal: Deploy to production, migrate data, validate system health, and set up backups/monitoring.

## 1) Deployment Preparation
- [ ] Confirm production environment is ready (Day 26 done)
- [ ] Freeze requirements/version set for deploy
- [ ] Tag release in git
- [ ] Backup current production database (if replacing)

## 2) Build & Release
- [ ] Build application package/image
- [ ] Deploy code to production server
- [ ] Install dependencies in production
- [ ] Apply `collectstatic`

## 3) Database Migration
- [ ] Run Django migrations in production
- [ ] Verify schema changes applied correctly
- [ ] Validate core tables (users, wallets, matches)
- [ ] Confirm database integrity post-migration

## 4) Data Migration (if moving from SQLite/PostgreSQL)
- [ ] Export legacy data
- [ ] Import into production database
- [ ] Validate data counts (users, wallets, matches)
- [ ] Spot-check critical records

## 5) Production Validation
- [ ] Admin login works
- [ ] Auth/login flow works
- [ ] Wallet deposit/withdraw flows work
- [ ] Match creation/joining works
- [ ] Evidence upload works
- [ ] Dispute resolution works

## 6) Logging & Monitoring
- [ ] Verify logs are writing correctly
- [ ] Verify error tracking is receiving events
- [ ] Configure alerts for errors/uptime

## 7) Backups & Rollback
- [ ] Confirm automated backups scheduled
- [ ] Test restore procedure
- [ ] Prepare rollback plan (code + DB)

## 8) Post-Deployment Checklist
- [ ] Verify DNS/SSL config
- [ ] Confirm static and media files serve correctly
- [ ] Verify API endpoints respond correctly
