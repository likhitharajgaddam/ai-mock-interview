#!/usr/bin/env bash
set -o errexit

echo '==> Python version check'
python --version

echo '==> Installing dependencies...'
pip install --upgrade pip
pip install -r requirements.txt

echo '==> Verifying psycopg2...'
python -c "import psycopg2; print('psycopg2 OK:', psycopg2.__version__)"

echo '==> Collecting static files...'
export DJANGO_SETTINGS_MODULE=ai_mock.settings
python manage.py collectstatic --no-input

echo '==> Running migrations...'
python manage.py migrate --no-input

echo '==> Build complete.'
