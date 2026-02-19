# Deployment Checklist

This checklist helps ensure your project is ready for production deployment.

## Pre-Deployment

### Code Organization ✅
- [x] Development files moved to `dev_files/` folder
- [x] Unnecessary files removed from root directory
- [x] Code committed to version control

### Database Setup
- [ ] PostgreSQL installed and running
- [ ] Database created (`playyarena_db` or your preferred name)
- [ ] Database user created with proper permissions
- [ ] Database connection tested
- [ ] Environment variables configured in `.env` file

### Environment Configuration
- [ ] `.env` file created from `local.env.example`
- [ ] `SECRET_KEY` generated and set (unique for production)
- [ ] `DEBUG=False` set
- [ ] `DJANGO_ALLOWED_HOSTS` configured with your domain
- [ ] `DJANGO_CSRF_TRUSTED_ORIGINS` configured with HTTPS URLs
- [ ] Database credentials configured
- [ ] Email settings configured
- [ ] SSL/HTTPS settings configured

### Dependencies
- [ ] `requirements.txt` up to date
- [ ] All dependencies installed in virtual environment
- [ ] `psycopg2-binary` included for PostgreSQL support

## Deployment Steps

### 1. Database Migration
```bash
python manage.py migrate
```

### 2. Create Superuser
```bash
python manage.py createsuperuser
```

### 3. Collect Static Files
```bash
python manage.py collectstatic --noinput
```

### 4. Test Database Connection
```bash
python manage.py dbshell
```

### 5. Verify Settings
- [ ] Database connection works
- [ ] Static files collected
- [ ] Media files directory exists (if using file uploads)
- [ ] Logging configured

## Post-Deployment

### Security
- [ ] `DEBUG=False` verified
- [ ] `SECRET_KEY` is unique and secure
- [ ] HTTPS enabled
- [ ] Security headers configured
- [ ] `.env` file not accessible via web server

### Functionality
- [ ] Admin panel accessible
- [ ] User registration/login works
- [ ] API endpoints functional
- [ ] Static files loading correctly
- [ ] Email sending works (if configured)

### Monitoring
- [ ] Error logging configured
- [ ] Monitoring tools set up (Sentry, etc.)
- [ ] Database backups configured
- [ ] Log rotation configured

## Files Not Needed for Deployment

The following files/folders are in `dev_files/` and are NOT needed for production:
- Setup scripts (`setup_postgresql.sh`, `setup_postgresql.ps1`)
- Test files (`test_rate_limiting.py`, `check_config.py`, etc.)
- Development documentation (`documents/` folder)
- Postman collections (`postman/` folder)
- Cache files (`cache/` folder - will be regenerated)
- Development logs (`rate_limit.log`)

## Essential Files for Deployment

These files MUST be present:
- `manage.py`
- `requirements.txt`
- `core/settings.py`
- `core/wsgi.py` (or `core/asgi.py` for async)
- `local.env.example` (for reference)
- `.env` (with production values - NOT in git)
- All Django app folders (`accounts/`, `matches/`, `wallet/`, etc.)
- `templates/` folder
- `static/` folder (or `staticfiles/` after collectstatic)
- `DEPLOYMENT.md` and `QUICK_DEPLOY.md` (for reference)

## Quick Reference

### Database Setup
See `QUICK_DEPLOY.md` for quick PostgreSQL setup.

### Full Deployment Guide
See `DEPLOYMENT.md` for detailed deployment instructions.

### Development Files
See `dev_files/README.md` for information about archived development files.

---

**Last Updated:** January 2025
