FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

# procps: `pgrep`, used by the Celery containers' healthchecks in production
RUN apt-get update && apt-get install -y --no-install-recommends procps && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-dev.txt ./
ARG INSTALL_DEV=false
RUN if [ "$INSTALL_DEV" = "true" ]; then pip install -r requirements-dev.txt; else pip install -r requirements.txt; fi

COPY . .
# Prod settings, so whitenoise writes the manifest that prod's CompressedManifestStaticFilesStorage
# needs (without it every {% static %} tag, e.g. all of Django admin, raises a 500). The secret
# key is a placeholder: collectstatic doesn't use it, but prod settings require one.
RUN DJANGO_SETTINGS_MODULE=config.settings.prod DJANGO_SECRET_KEY=collectstatic-only python manage.py collectstatic --noinput

CMD ["sh", "-c", "gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers 2 --timeout 120"]
