from .base import *  # noqa: F403

DEBUG = False
SECRET_KEY = env("DJANGO_SECRET_KEY")  # noqa: F405  (required in prod)

# Render sets RENDER_EXTERNAL_HOSTNAME for web services; trust it automatically.
if render_host := env("RENDER_EXTERNAL_HOSTNAME", default=""):  # noqa: F405
    ALLOWED_HOSTS = [*ALLOWED_HOSTS, render_host]  # noqa: F405
    CSRF_TRUSTED_ORIGINS = [*CSRF_TRUSTED_ORIGINS, f"https://{render_host}"]  # noqa: F405

# Don't publish the API surface: the whole endpoint map would be readable by anyone.
# Set DJANGO_API_DOCS=true on a staging service to bring it back there.
API_DOCS_ENABLED = env.bool("DJANGO_API_DOCS", default=False)  # noqa: F405

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=True)  # noqa: F405
SECURE_REDIRECT_EXEMPT = [r"^api/health/$"]  # health checks may come over plain HTTP
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = env.int("DJANGO_HSTS_SECONDS", default=0)  # noqa: F405  (raise once HTTPS is confirmed)
SECURE_CONTENT_TYPE_NOSNIFF = True

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
