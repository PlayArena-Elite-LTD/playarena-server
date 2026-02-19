# PlayyArena Deployment Guide

This guide will help you deploy PlayyArena to production with PostgreSQL.

## Table of Contents
1. [Prerequisites](#prerequisites)
2. [PostgreSQL Setup](#postgresql-setup)
3. [Environment Configuration](#environment-configuration)
4. [Database Migration](#database-migration)
5. [Deployment Steps](#deployment-steps)
6. [Post-Deployment Checklist](#post-deployment-checklist)

---

## Prerequisites

- Python 3.10+ installed
- PostgreSQL 12+ installed and running
- pip and virtualenv (or venv)
- Git (for version control)
- Your deployment platform account (e.g., PythonAnywhere, Heroku, AWS, etc.)

---

## PostgreSQL Setup

### 1. Install PostgreSQL

#### On Ubuntu/Debian:
```bash
sudo apt update
sudo apt install postgresql postgresql-contrib
sudo systemctl start postgresql
sudo systemctl enable postgresql
```

#### On Windows:
Download and install from: https://www.postgresql.org/download/windows/

#### On macOS:
```bash
brew install postgresql
brew services start postgresql
```

### 2. Create PostgreSQL Database and User

#### Option A: Using psql (Command Line)

```bash
# Switch to postgres user (Linux/Mac)
sudo -u postgres psql

# Or on Windows, open "SQL Shell (psql)" from Start Menu
```

Then run these SQL commands:

```sql
-- Create database
CREATE DATABASE playyarena_db;

-- Create user with password
CREATE USER playyarena_user WITH PASSWORD 'your_secure_password_here';

-- Grant privileges
ALTER ROLE playyarena_user SET client_encoding TO 'utf8';
ALTER ROLE playyarena_user SET default_transaction_isolation TO 'read committed';
ALTER ROLE playyarena_user SET timezone TO 'UTC';

-- Grant all privileges on database
GRANT ALL PRIVILEGES ON DATABASE playyarena_db TO playyarena_user;

-- Connect to the database
\c playyarena_db

-- Grant schema privileges (PostgreSQL 15+)
GRANT ALL ON SCHEMA public TO playyarena_user;

-- Exit psql
\q
```

#### Option B: Using pgAdmin (GUI)

1. Open pgAdmin
2. Right-click on "Databases" → Create → Database
   - Name: `playyarena_db`
   - Owner: `postgres` (or create new user)
3. Right-click on "Login/Group Roles" → Create → Login/Group Role
   - Name: `playyarena_user`
   - Password: Set a secure password
   - Privileges: Check "Can login?"
4. Right-click on `playyarena_db` → Properties → Security
   - Add `playyarena_user` with ALL privileges

### 3. Test PostgreSQL Connection

```bash
# Test connection from command line
psql -h localhost -U playyarena_user -d playyarena_db

# If prompted for password, enter the password you set
# You should see: playyarena_db=>
# Type \q to exit
```

---

## Environment Configuration

### 1. Create Production Environment File

Copy the example environment file:

```bash
cp local.env.example .env
```

Or create a new `.env` file in your project root with these variables:

```bash
# ============================================================================
# CRITICAL SECURITY SETTINGS (REQUIRED FOR PRODUCTION)
# ============================================================================

# Generate a new secret key for production:
# python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
SECRET_KEY=your_generated_secret_key_here

# Debug Mode (MUST be False in production)
DEBUG=false

# Allowed Hosts (your domain)
DJANGO_ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com

# CSRF Trusted Origins (HTTPS URLs)
DJANGO_CSRF_TRUSTED_ORIGINS=https://yourdomain.com,https://www.yourdomain.com

# ============================================================================
# DATABASE CONFIGURATION
# ============================================================================

# PostgreSQL Configuration
DB_ENGINE=django.db.backends.postgresql
DB_NAME=playyarena_db
DB_USER=playyarena_user
DB_PASSWORD=your_secure_password_here
DB_HOST=localhost
DB_PORT=5432

# For remote PostgreSQL (e.g., AWS RDS, Heroku Postgres):
# DB_HOST=your-db-host.amazonaws.com
# DB_PORT=5432

# ============================================================================
# EMAIL CONFIGURATION
# ============================================================================

EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your-app-specific-password
EMAIL_USE_TLS=true
EMAIL_USE_SSL=false

ADMIN_EMAIL=admin@yourdomain.com
SERVER_EMAIL=noreply@yourdomain.com
DEFAULT_FROM_EMAIL=noreply@yourdomain.com

# ============================================================================
# SSL & SECURITY (Production)
# ============================================================================

SECURE_SSL_REDIRECT=true

# ============================================================================
# CACHE & REDIS CONFIGURATION (Optional but Recommended)
# ============================================================================

REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=1

# ============================================================================
# MONITORING & ERROR TRACKING (Optional)
# ============================================================================

SENTRY_DSN=your-sentry-dsn-here
SENTRY_ENVIRONMENT=production
```

### 2. Secure Your Environment File

**IMPORTANT:** Never commit `.env` to version control!

```bash
# Ensure .env is in .gitignore
echo ".env" >> .gitignore
echo "*.env" >> .gitignore
echo "local.env" >> .gitignore
```

---

## Database Migration

### 1. Install Dependencies

```bash
# Create virtual environment (if not already created)
python -m venv venv

# Activate virtual environment
# On Windows:
venv\Scripts\activate
# On Linux/Mac:
source venv/bin/activate

# Install requirements
pip install -r requirements.txt
```

### 2. Run Migrations

```bash
# Make migrations (if you have model changes)
python manage.py makemigrations

# Apply migrations to PostgreSQL
python manage.py migrate

# Create superuser (if needed)
python manage.py createsuperuser
```

### 3. Collect Static Files

```bash
python manage.py collectstatic --noinput
```

### 4. Test Database Connection

```bash
# Test database connection
python manage.py dbshell

# You should see PostgreSQL prompt: playyarena_db=>
# Type \q to exit
```

---

## Deployment Steps

### Option 1: PythonAnywhere

1. **Upload your code:**
   ```bash
   # On your local machine, commit and push to Git
   git add .
   git commit -m "Prepare for deployment"
   git push origin main
   
   # On PythonAnywhere, clone your repo
   git clone https://github.com/yourusername/playyarena.git
   ```

2. **Set up virtual environment:**
   ```bash
   cd playyarena
   python3.10 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

3. **Configure PostgreSQL:**
   - Go to Databases tab in PythonAnywhere dashboard
   - Create a new PostgreSQL database
   - Note the database credentials
   - Update your `.env` file with these credentials

4. **Set environment variables:**
   - Go to Web tab → WSGI configuration file
   - Add environment variables or load from `.env` file

5. **Run migrations:**
   ```bash
   python manage.py migrate
   python manage.py collectstatic --noinput
   ```

6. **Configure WSGI:**
   - Update WSGI file to point to your Django app
   - Reload web app

### Option 2: Heroku

1. **Install Heroku CLI:**
   ```bash
   # Download from: https://devcenter.heroku.com/articles/heroku-cli
   ```

2. **Create Heroku app:**
   ```bash
   heroku login
   heroku create your-app-name
   ```

3. **Add PostgreSQL addon:**
   ```bash
   heroku addons:create heroku-postgresql:hobby-dev
   ```

4. **Set environment variables:**
   ```bash
   heroku config:set SECRET_KEY="your-secret-key"
   heroku config:set DEBUG="false"
   heroku config:set DJANGO_ALLOWED_HOSTS="your-app-name.herokuapp.com"
   heroku config:set DJANGO_CSRF_TRUSTED_ORIGINS="https://your-app-name.herokuapp.com"
   ```

5. **Deploy:**
   ```bash
   git push heroku main
   heroku run python manage.py migrate
   heroku run python manage.py createsuperuser
   ```

### Option 3: AWS EC2 / VPS

1. **SSH into your server:**
   ```bash
   ssh user@your-server-ip
   ```

2. **Install dependencies:**
   ```bash
   sudo apt update
   sudo apt install python3-pip python3-venv postgresql nginx
   ```

3. **Set up PostgreSQL (see PostgreSQL Setup section above)**

4. **Clone and configure:**
   ```bash
   git clone https://github.com/yourusername/playyarena.git
   cd playyarena
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

5. **Configure environment:**
   ```bash
   cp local.env.example .env
   nano .env  # Edit with your production values
   ```

6. **Run migrations:**
   ```bash
   python manage.py migrate
   python manage.py collectstatic --noinput
   ```

7. **Set up Gunicorn:**
   ```bash
   # Create gunicorn service file
   sudo nano /etc/systemd/system/playyarena.service
   ```

   Add this content:
   ```ini
   [Unit]
   Description=PlayyArena Gunicorn daemon
   After=network.target

   [Service]
   User=www-data
   Group=www-data
   WorkingDirectory=/path/to/playyarena
   Environment="PATH=/path/to/playyarena/venv/bin"
   ExecStart=/path/to/playyarena/venv/bin/gunicorn \
       --workers 3 \
       --bind unix:/path/to/playyarena/playyarena.sock \
       core.wsgi:application

   [Install]
   WantedBy=multi-user.target
   ```

8. **Start services:**
   ```bash
   sudo systemctl start playyarena
   sudo systemctl enable playyarena
   ```

9. **Configure Nginx:**
   ```bash
   sudo nano /etc/nginx/sites-available/playyarena
   ```

   Add this configuration:
   ```nginx
   server {
       listen 80;
       server_name yourdomain.com www.yourdomain.com;

       location /static/ {
           alias /path/to/playyarena/staticfiles/;
       }

       location /media/ {
           alias /path/to/playyarena/media/;
       }

       location / {
           include proxy_params;
           proxy_pass http://unix:/path/to/playyarena/playyarena.sock;
       }
   }
   ```

   Enable site:
   ```bash
   sudo ln -s /etc/nginx/sites-available/playyarena /etc/nginx/sites-enabled/
   sudo nginx -t
   sudo systemctl restart nginx
   ```

10. **Set up SSL (Let's Encrypt):**
    ```bash
    sudo apt install certbot python3-certbot-nginx
    sudo certbot --nginx -d yourdomain.com -d www.yourdomain.com
    ```

---

## Post-Deployment Checklist

- [ ] Database migrations completed successfully
- [ ] Static files collected (`collectstatic`)
- [ ] Environment variables set correctly
- [ ] `DEBUG=False` in production
- [ ] `SECRET_KEY` is unique and secure
- [ ] `ALLOWED_HOSTS` includes your domain
- [ ] `CSRF_TRUSTED_ORIGINS` includes HTTPS URLs
- [ ] PostgreSQL connection working
- [ ] Superuser account created
- [ ] SSL/HTTPS configured
- [ ] Static files serving correctly
- [ ] Email configuration tested
- [ ] Error logging configured (Sentry or similar)
- [ ] Backup strategy in place
- [ ] Monitoring set up

---

## Troubleshooting

### Database Connection Errors

**Error: "could not connect to server"**
- Check PostgreSQL is running: `sudo systemctl status postgresql`
- Verify `DB_HOST` and `DB_PORT` in `.env`
- Check firewall rules allow PostgreSQL port (5432)

**Error: "password authentication failed"**
- Verify `DB_USER` and `DB_PASSWORD` in `.env`
- Reset PostgreSQL password if needed

**Error: "database does not exist"**
- Create database: `CREATE DATABASE playyarena_db;`
- Verify `DB_NAME` in `.env`

### Migration Errors

**Error: "relation already exists"**
```bash
# Reset migrations (CAUTION: Only in development!)
python manage.py migrate --fake-initial
```

**Error: "no such table"**
```bash
# Run migrations
python manage.py migrate
```

### Static Files Not Loading

```bash
# Recollect static files
python manage.py collectstatic --noinput --clear

# Check STATIC_ROOT and STATIC_URL in settings.py
# Verify static files directory permissions
```

---

## Security Best Practices

1. **Never commit `.env` files** to version control
2. **Use strong passwords** for database and admin accounts
3. **Enable HTTPS** in production
4. **Set `DEBUG=False`** in production
5. **Use environment variables** for all secrets
6. **Regular backups** of PostgreSQL database
7. **Keep dependencies updated**: `pip list --outdated`
8. **Monitor error logs** (Sentry, etc.)
9. **Use PostgreSQL connection pooling** for high traffic
10. **Set up database backups** (automated daily backups)

---

## Database Backup and Restore

### Backup:
```bash
pg_dump -h localhost -U playyarena_user -d playyarena_db > backup_$(date +%Y%m%d).sql
```

### Restore:
```bash
psql -h localhost -U playyarena_user -d playyarena_db < backup_20250101.sql
```

---

## Support

For issues or questions, check:
- Django Documentation: https://docs.djangoproject.com/
- PostgreSQL Documentation: https://www.postgresql.org/docs/
- Your deployment platform's documentation

---

**Last Updated:** January 2025
