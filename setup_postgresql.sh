#!/bin/bash
# PostgreSQL Setup Script for PlayyArena
# This script helps set up PostgreSQL database and user for deployment

set -e  # Exit on error

echo "=========================================="
echo "PlayyArena PostgreSQL Setup"
echo "=========================================="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if running as root
if [ "$EUID" -eq 0 ]; then 
    echo -e "${RED}Error: Do not run this script as root. Run as a user with sudo privileges.${NC}"
    exit 1
fi

# Check if PostgreSQL is installed
if ! command -v psql &> /dev/null; then
    echo -e "${YELLOW}PostgreSQL is not installed. Installing...${NC}"
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        sudo apt update
        sudo apt install -y postgresql postgresql-contrib
        sudo systemctl start postgresql
        sudo systemctl enable postgresql
    elif [[ "$OSTYPE" == "darwin"* ]]; then
        echo "Please install PostgreSQL using Homebrew:"
        echo "  brew install postgresql"
        echo "  brew services start postgresql"
        exit 1
    else
        echo "Please install PostgreSQL manually for your operating system."
        exit 1
    fi
fi

echo -e "${GREEN}PostgreSQL is installed.${NC}"
echo ""

# Prompt for database configuration
read -p "Enter database name [playyarena_db]: " DB_NAME
DB_NAME=${DB_NAME:-playyarena_db}

read -p "Enter database user [playyarena_user]: " DB_USER
DB_USER=${DB_USER:-playyarena_user}

read -sp "Enter database password: " DB_PASSWORD
echo ""

read -p "Enter database host [localhost]: " DB_HOST
DB_HOST=${DB_HOST:-localhost}

read -p "Enter database port [5432]: " DB_PORT
DB_PORT=${DB_PORT:-5432}

echo ""
echo "=========================================="
echo "Creating PostgreSQL database and user..."
echo "=========================================="
echo ""

# Create PostgreSQL commands
SQL_COMMANDS="
-- Create database
CREATE DATABASE ${DB_NAME};

-- Create user
CREATE USER ${DB_USER} WITH PASSWORD '${DB_PASSWORD}';

-- Set user privileges
ALTER ROLE ${DB_USER} SET client_encoding TO 'utf8';
ALTER ROLE ${DB_USER} SET default_transaction_isolation TO 'read committed';
ALTER ROLE ${DB_USER} SET timezone TO 'UTC';

-- Grant privileges
GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER};
"

# Execute SQL commands
echo "Running PostgreSQL commands..."
sudo -u postgres psql <<EOF
${SQL_COMMANDS}
\c ${DB_NAME}
GRANT ALL ON SCHEMA public TO ${DB_USER};
\q
EOF

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Database and user created successfully!${NC}"
else
    echo -e "${RED}✗ Error creating database or user${NC}"
    exit 1
fi

echo ""
echo "=========================================="
echo "Testing connection..."
echo "=========================================="
echo ""

# Test connection
PGPASSWORD=${DB_PASSWORD} psql -h ${DB_HOST} -p ${DB_PORT} -U ${DB_USER} -d ${DB_NAME} -c "SELECT version();" > /dev/null 2>&1

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Connection test successful!${NC}"
else
    echo -e "${YELLOW}⚠ Connection test failed. Please verify your credentials.${NC}"
fi

echo ""
echo "=========================================="
echo "Environment Variables"
echo "=========================================="
echo ""
echo "Add these to your .env file:"
echo ""
echo "DB_ENGINE=django.db.backends.postgresql"
echo "DB_NAME=${DB_NAME}"
echo "DB_USER=${DB_USER}"
echo "DB_PASSWORD=${DB_PASSWORD}"
echo "DB_HOST=${DB_HOST}"
echo "DB_PORT=${DB_PORT}"
echo ""
echo -e "${GREEN}Setup complete!${NC}"
echo ""
