from .base import *  # noqa: F403

SECRET_KEY = "test"
ANTHROPIC_API_KEY = "test-key"
LANGSMITH_TRACING = False
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
MIDDLEWARE = [m for m in MIDDLEWARE if "whitenoise" not in m]  # noqa: F405
