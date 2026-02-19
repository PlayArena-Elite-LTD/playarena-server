# PostgreSQL Setup Script for PlayyArena (Windows PowerShell)
# This script helps set up PostgreSQL database and user for deployment

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "PlayyArena PostgreSQL Setup" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# Check if PostgreSQL is installed
try {
    $psqlVersion = & psql --version 2>$null
    Write-Host "PostgreSQL is installed: $psqlVersion" -ForegroundColor Green
} catch {
    Write-Host "PostgreSQL is not installed or not in PATH." -ForegroundColor Yellow
    Write-Host "Please install PostgreSQL from: https://www.postgresql.org/download/windows/" -ForegroundColor Yellow
    Write-Host "After installation, ensure PostgreSQL bin directory is in your PATH." -ForegroundColor Yellow
    exit 1
}

# Prompt for database configuration
$DB_NAME = Read-Host "Enter database name [playyarena_db]"
if ([string]::IsNullOrWhiteSpace($DB_NAME)) { $DB_NAME = "playyarena_db" }

$DB_USER = Read-Host "Enter database user [playyarena_user]"
if ([string]::IsNullOrWhiteSpace($DB_USER)) { $DB_USER = "playyarena_user" }

$securePassword = Read-Host "Enter database password" -AsSecureString
$BSTR = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
$DB_PASSWORD = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($BSTR)

$DB_HOST = Read-Host "Enter database host [localhost]"
if ([string]::IsNullOrWhiteSpace($DB_HOST)) { $DB_HOST = "localhost" }

$DB_PORT = Read-Host "Enter database port [5432]"
if ([string]::IsNullOrWhiteSpace($DB_PORT)) { $DB_PORT = "5432" }

Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "Creating PostgreSQL database and user..." -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# Create SQL file
$sqlFile = "$env:TEMP\playyarena_setup.sql"
@"
-- Create database
CREATE DATABASE $DB_NAME;

-- Create user
CREATE USER $DB_USER WITH PASSWORD '$DB_PASSWORD';

-- Set user privileges
ALTER ROLE $DB_USER SET client_encoding TO 'utf8';
ALTER ROLE $DB_USER SET default_transaction_isolation TO 'read committed';
ALTER ROLE $DB_USER SET timezone TO 'UTC';

-- Grant privileges
GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;

-- Connect to database and grant schema privileges
\c $DB_NAME
GRANT ALL ON SCHEMA public TO $DB_USER;
"@ | Out-File -FilePath $sqlFile -Encoding UTF8

# Execute SQL commands
Write-Host "Running PostgreSQL commands..." -ForegroundColor Yellow
try {
    # Set PGPASSWORD environment variable for this session
    $env:PGPASSWORD = $DB_PASSWORD
    
    # Run psql commands
    & psql -U postgres -f $sqlFile
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✓ Database and user created successfully!" -ForegroundColor Green
    } else {
        Write-Host "✗ Error creating database or user" -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Host "Error: $_" -ForegroundColor Red
    Write-Host "Please ensure PostgreSQL is running and you have the correct permissions." -ForegroundColor Yellow
    exit 1
} finally {
    # Clean up
    Remove-Item $sqlFile -ErrorAction SilentlyContinue
    Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "Testing connection..." -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# Test connection
$env:PGPASSWORD = $DB_PASSWORD
try {
    $testResult = & psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME -c "SELECT version();" 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✓ Connection test successful!" -ForegroundColor Green
    } else {
        Write-Host "⚠ Connection test failed. Please verify your credentials." -ForegroundColor Yellow
    }
} catch {
    Write-Host "⚠ Connection test failed: $_" -ForegroundColor Yellow
} finally {
    Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "Environment Variables" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Add these to your .env file:" -ForegroundColor Yellow
Write-Host ""
Write-Host "DB_ENGINE=django.db.backends.postgresql"
Write-Host "DB_NAME=$DB_NAME"
Write-Host "DB_USER=$DB_USER"
Write-Host "DB_PASSWORD=$DB_PASSWORD"
Write-Host "DB_HOST=$DB_HOST"
Write-Host "DB_PORT=$DB_PORT"
Write-Host ""
Write-Host "Setup complete!" -ForegroundColor Green
Write-Host ""
