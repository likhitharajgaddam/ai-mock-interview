#!/usr/bin/env bash
# Render build script — exits immediately on any error
set -o errexit

echo "==> Python version"
python --version

echo "==> Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

echo "==> Collecting static files..."
DJANGO_SETTINGS_MODULE=ai_mock.settings python manage.py collectstatic --no-input

echo "==> Running migrations..."
DJANGO_SETTINGS_MODULE=ai_mock.settings python manage.py migrate --no-input

echo "==> Build complete."
