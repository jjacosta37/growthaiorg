import logging
import os

from .base import *  # noqa: F403

SECRET_KEY = "test"
ANTHROPIC_API_KEY = "test-key"
LANGSMITH_TRACING = False

# Tests must never reach LangSmith. A developer's .env commonly has LANGSMITH_TRACING=true,
# and langsmith reads that env var itself — independently of the Django setting above — so
# the tracing tests would ship real runs and its background thread would log 403s after the
# session ended. Point it at a dead address and keep its logger quiet.
os.environ["LANGSMITH_ENDPOINT"] = "http://127.0.0.1:1"
os.environ.setdefault("LANGSMITH_API_KEY", "test-key")
logging.getLogger("langsmith").setLevel(logging.CRITICAL)
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
MIDDLEWARE = [m for m in MIDDLEWARE if "whitenoise" not in m]  # noqa: F405
