import os
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

# -----------------------------------------------------------------------
# Security
# -----------------------------------------------------------------------
SECRET_KEY = os.environ.get(
    "SECRET_KEY",
    "django-insecure-36an!(#0&^^3)#-d-q^iw4yb1i-t8$zl(^xdq1&$rf+b_(j^6-",
)

DEBUG = os.environ.get("DEBUG", "False") == "True"

# -----------------------------------------------------------------------
# Hosts — supports Railway, Render, and local dev
# -----------------------------------------------------------------------
ALLOWED_HOSTS = [
    "127.0.0.1",
    "localhost",
    "0.0.0.0",
    ".railway.app",
    ".onrender.com",
]

# Append any platform-specific domain injected at runtime
for _env_var in ("RAILWAY_PUBLIC_DOMAIN", "RENDER_EXTERNAL_HOSTNAME"):
    _domain = os.environ.get(_env_var, "")
    if _domain and _domain not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(_domain)

# -----------------------------------------------------------------------
# CSRF trusted origins — Railway + Render
# -----------------------------------------------------------------------
CSRF_TRUSTED_ORIGINS = [
    "https://*.railway.app",
    "https://*.up.railway.app",
    "https://*.onrender.com",
]

for _env_var in ("RAILWAY_PUBLIC_DOMAIN", "RENDER_EXTERNAL_HOSTNAME"):
    _domain = os.environ.get(_env_var, "")
    if _domain:
        CSRF_TRUSTED_ORIGINS.append(f"https://{_domain}")

# -----------------------------------------------------------------------
# Application definition
# -----------------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "users",
    "interviews",
    "dashboard",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "ai_mock.middleware.AutoLogoutMiddleware",
]

# -----------------------------------------------------------------------
# CORS / cookie settings (portfolio preview support)
# -----------------------------------------------------------------------
X_FRAME_OPTIONS = "ALLOWALL"
SECURE_CROSS_ORIGIN_OPENER_POLICY = None
CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_CREDENTIALS = True
CSRF_COOKIE_SAMESITE = "None"
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SAMESITE = "None"
SESSION_COOKIE_SECURE = True

# -----------------------------------------------------------------------
# URLs / WSGI
# -----------------------------------------------------------------------
ROOT_URLCONF = "ai_mock.urls"
WSGI_APPLICATION = "ai_mock.wsgi.application"

# -----------------------------------------------------------------------
# Templates
# -----------------------------------------------------------------------
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# -----------------------------------------------------------------------
# Database — PostgreSQL via DATABASE_URL env var, SQLite fallback
# -----------------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

_db_url = os.environ.get("DATABASE_URL", "")
if _db_url:
    DATABASES["default"] = dj_database_url.parse(
        _db_url, conn_max_age=600, ssl_require=True
    )

# -----------------------------------------------------------------------
# Password validation
# -----------------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# -----------------------------------------------------------------------
# Internationalisation
# -----------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# -----------------------------------------------------------------------
# Static files
# -----------------------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"
WHITENOISE_USE_FINDERS = True
WHITENOISE_MANIFEST_STRICT = False

# -----------------------------------------------------------------------
# Auth redirects
# -----------------------------------------------------------------------
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "select_role"
LOGOUT_REDIRECT_URL = "login"

# -----------------------------------------------------------------------
# Logging — surfaces AI errors in Render / Railway log streams
# -----------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[{levelname}] {asctime} {name}: {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "interviews.evaluator": {
            "handlers": ["console"],
            "level": "DEBUG",
            "propagate": False,
        },
        "interviews.views": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
