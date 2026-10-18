"""MISTERCHIP settings: credentials always supplied outside version control."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

DEBUG = os.getenv("DJANGO_DEBUG", "0") == "1"
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "django-insecure-local-development-only-not-for-production"
    else:
        raise RuntimeError("DJANGO_SECRET_KEY is required when DEBUG is disabled.")

ALLOWED_HOSTS = [v.strip() for v in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if v.strip()]
CSRF_TRUSTED_ORIGINS = [v.strip() for v in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if v.strip()]
# Caddy is the only public entry point; Docker remains bound to 127.0.0.1.
if os.getenv("DJANGO_TRUST_PROXY_SSL", "0") == "1":
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "catalog",
    "editorial",
    "projects",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "config.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.debug",
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"
AUTH_USER_MODEL = "accounts.User"
DATABASES = {"default": {
    "ENGINE": "django.db.backends.postgresql",
    "NAME": os.getenv("DB_NAME", "misterchip"),
    "USER": os.getenv("DB_USER", "misterchip"),
    "PASSWORD": os.getenv("DB_PASSWORD", ""),
    "HOST": os.getenv("DB_HOST", "localhost"),
    "PORT": os.getenv("DB_PORT", "5432"),
    "CONN_MAX_AGE": 60,
}}
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LANGUAGE_CODE = "ru"
TIME_ZONE = "Europe/Moscow"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {"staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"}}
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
EMAIL_BACKEND = os.getenv(
    "DJANGO_EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend",
)
EMAIL_HOST = os.getenv("EMAIL_HOST", "localhost")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "1") == "1"
EMAIL_TIMEOUT = 10
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "MISTERCHIP <noreply@example.invalid>")
if not DEBUG and EMAIL_BACKEND == "django.core.mail.backends.console.EmailBackend":
    raise RuntimeError("Configure a real email backend before running without DEBUG.")
PASSWORD_RESET_TIMEOUT = 3600

# Authentication limit counts must be shared by every process and server.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": os.getenv("REDIS_URL", "redis://localhost:6379/1"),
    }
}
# For a *localhost-only SSH tunnel* during the private testing phase.
# Never enable this mode for a publicly reachable HTTP service.
STAGING_SSH_TUNNEL = os.getenv("DJANGO_STAGING_SSH_TUNNEL", "0") == "1"
if STAGING_SSH_TUNNEL:
    if DEBUG or set(ALLOWED_HOSTS) - {"localhost", "127.0.0.1", "[::1]"}:
        raise RuntimeError("SSH-tunnel staging requires DEBUG=0 and loopback-only hosts.")
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
if not DEBUG:
    SESSION_COOKIE_SECURE = not STAGING_SSH_TUNNEL
    CSRF_COOKIE_SECURE = not STAGING_SSH_TUNNEL
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_SSL_REDIRECT = (
        False if STAGING_SSH_TUNNEL else os.getenv("DJANGO_SECURE_SSL_REDIRECT", "1") == "1"
    )
    SECURE_HSTS_SECONDS = 0 if STAGING_SSH_TUNNEL else int(os.getenv("DJANGO_HSTS_SECONDS", "0"))


LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "account_dashboard"

# Django's file-based backend is supported for local-only staging verification emails.
EMAIL_FILE_PATH = os.getenv("EMAIL_FILE_PATH", str(BASE_DIR / "private_mail"))
