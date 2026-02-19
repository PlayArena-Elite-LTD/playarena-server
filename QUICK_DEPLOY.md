# Quick PostgreSQL Deployment Guide

## Quick Setup (5 Minutes)

### 1. Install PostgreSQL

**Windows:**
- Download from: https://www.postgresql.org/download/windows/
- Install with default settings
- Remember the postgres user password you set

**Linux (Ubuntu/Debian):**
```bash
sudo apt update
sudo apt install postgresql postgresql-contrib
sudo systemctl start postgresql
```

**macOS:**
```bash
brew install postgresql
brew services start postgresql
```

### 2. Create Database and User

**Option A: Use Setup Script**

**Linux/Mac:**
```bash
chmod +x setup_postgresql.sh
./setup_postgresql.sh
```

**Windows (PowerShell):**
```powershell
.\setup_postgresql.ps1
```

**Option B: Manual Setup**

Open PostgreSQL command line (`psql` on Linux/Mac, or "SQL Shell (psql)" on Windows):

```sql
-- Connect as postgres user
-- On Linux/Mac: sudo -u postgres psql
-- On Windows: Just open SQL Shell and enter postgres user password

-- Create database
CREATE DATABASE playyarena_db;

-- Create user
CREATE USER playyarena_user WITH PASSWORD 'your_secure_password';

-- Grant privileges
ALTER ROLE playyarena_user SET client_encoding TO 'utf8';
ALTER ROLE playyarena_user SET default_transaction_isolation TO 'read committed';
ALTER ROLE playyarena_user SET timezone TO 'UTC';
GRANT ALL PRIVILEGES ON DATABASE playyarena_db TO playyarena_user;

-- Connect to database
\c playyarena_db

-- Grant schema privileges (PostgreSQL 15+)
GRANT ALL ON SCHEMA public TO playyarena_user;

-- Exit
\q
```

### 3. Configure Environment Variables

Create or update your `.env` file:

```bash
# Database Configuration
DB_ENGINE=django.db.backends.postgresql
DB_NAME=playyarena_db
DB_USER=playyarena_user
DB_PASSWORD=your_secure_password
DB_HOST=localhost
DB_PORT=5432

# Production Settings
DEBUG=false
SECRET_KEY=your_generated_secret_key_here
DJANGO_ALLOWED_HOSTS=yourdomain.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://yourdomain.com
```

### 4. Run Migrations

```bash
# Activate virtual environment
source venv/bin/activate  # Linux/Mac
# OR
venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt

# Run migrations
python manage.py migrate

# Create superuser
python manage.py createsuperuser

# Collect static files
python manage.py collectstatic --noinput
```

### 5. Test Connection

```bash
python manage.py dbshell
# You should see: playyarena_db=>
# Type \q to exit
```

## Common Issues

### "could not connect to server"
- Check PostgreSQL is running: `sudo systemctl status postgresql` (Linux)
- Verify `DB_HOST` and `DB_PORT` in `.env`
- Check firewall allows port 5432

### "password authentication failed"
- Verify `DB_USER` and `DB_PASSWORD` in `.env`
- Reset password: `ALTER USER playyarena_user WITH PASSWORD 'new_password';`

### "database does not exist"
- Create database: `CREATE DATABASE playyarena_db;`
- Verify `DB_NAME` in `.env`

## Remote PostgreSQL (AWS RDS, Heroku, etc.)

For remote PostgreSQL databases, update your `.env`:

```bash
DB_HOST=your-db-instance.region.rds.amazonaws.com
DB_PORT=5432
DB_NAME=your_database_name
DB_USER=your_username
DB_PASSWORD=your_password
```

## Next Steps

1. ✅ PostgreSQL installed
2. ✅ Database and user created
3. ✅ Environment variables configured
4. ✅ Migrations run
5. 📖 Read `DEPLOYMENT.md` for full deployment guide
6. 🚀 Deploy to your hosting platform

## Security Checklist

- [ ] Strong database password set
- [ ] `DEBUG=False` in production
- [ ] Unique `SECRET_KEY` generated
- [ ] `.env` file not committed to Git
- [ ] HTTPS enabled
- [ ] Database backups configured

---

**Need Help?** See `DEPLOYMENT.md` for detailed instructions.
