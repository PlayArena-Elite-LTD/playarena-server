#!/usr/bin/env bash
# Azure App Service startup command for the Arena2 Django backend.
# Applies DB migrations and collects static files, then launches gunicorn.
set -e

echo "Running database migrations..."
python manage.py migrate --noinput

echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Starting gunicorn..."
exec gunicorn core.wsgi:application \
  --bind=0.0.0.0:8000 \
  --timeout 30 \
  --workers 3
