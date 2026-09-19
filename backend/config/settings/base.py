from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR.parent / ".env", overwrite=False)

SECRET_KEY = env("DJANGO_SECRET_KEY", default="dev-insecure-change-me")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    "django_celery_beat",
    "llm",
    "apps.core",
    "apps.policy",
    "apps.agents",
    "apps.context",
    "apps.inbox",
    "apps.reddit",
    "apps.content",
    "apps.xagent",
    "apps.stats",
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
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
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

DATABASES = {"default": env.db("DATABASE_URL", default="postgres://sift:sift@localhost:5433/sift")}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = False
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.LimitOffsetPagination",
    "PAGE_SIZE": 50,
}
SPECTACULAR_SETTINGS = {
    "TITLE": "Sift API",
    "VERSION": "0.1.0",
    # Stable enum names for the generated frontend types (instead of Status393Enum and similar).
    "ENUM_NAME_OVERRIDES": {
        "DraftKindEnum": "apps.inbox.models.DraftKind",
        "DraftStatusEnum": "apps.inbox.models.Draft.Status",
        "DismissReasonEnum": "apps.inbox.models.Draft.DismissReason",
        "DraftVersionSourceEnum": "apps.inbox.models.DraftVersion.Source",
        "RunKindEnum": "apps.agents.models.AgentRun.Kind",
        "RunStatusEnum": "apps.agents.models.AgentRun.Status",
        "RunTriggerEnum": "apps.agents.models.AgentRun.Trigger",
        "RunEventLevelEnum": "apps.agents.models.RunEvent.Level",
        "DocKindEnum": "apps.context.models.DocKind",
        "DocSourceEnum": "apps.context.models.DocSource",
        "PolicySourceEnum": "apps.policy.models.ContentPolicy.Source",
        "BlogTopicStatusEnum": "apps.content.models.BlogTopic.Status",
    },
}

# Celery
CELERY_BROKER_URL = env("REDIS_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = None
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"
CELERY_TIMEZONE = TIME_ZONE

# LLM
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY", default="")
LLM_MODELS = {
    "fast": env("LLM_MODEL_FAST", default="claude-haiku-4-5-20251001"),
    "writer": env("LLM_MODEL_WRITER", default="claude-sonnet-5"),
}
# USD per million tokens. Cache writes (5m TTL) bill at 1.25x input, cache reads at 0.1x.
LLM_PRICING = {
    "claude-haiku-4-5-20251001": {"input": 1.00, "output": 5.00},
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00},
    "claude-sonnet-5": {"input": 2.00, "output": 10.00},
}
LLM_CACHE_WRITE_MULTIPLIER = 1.25
LLM_CACHE_READ_MULTIPLIER = 0.10
LLM_BATCH_DISCOUNT = 0.50
LLM_WEB_SEARCH_USD_PER_REQUEST = 0.01
LLM_MAX_RETRIES = env.int("LLM_MAX_RETRIES", default=3)
LLM_TIMEOUT_SECONDS = env.float("LLM_TIMEOUT_SECONDS", default=600.0)
PROMPTS_DIR = BASE_DIR / "prompts"

# LangSmith reads LANGSMITH_TRACING / LANGSMITH_API_KEY / LANGSMITH_PROJECT from the environment.
LANGSMITH_TRACING = env.bool("LANGSMITH_TRACING", default=False)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
    "loggers": {
        "trafilatura": {"level": "ERROR"},  # warns "discarding data" for every thin page
        "httpx": {"level": "WARNING"},
    },
}

# Onboarding crawl
CRAWL_MAX_PAGES = env.int("CRAWL_MAX_PAGES", default=40)
CRAWL_DELAY_SECONDS = env.float("CRAWL_DELAY_SECONDS", default=0.2)
CONTEXT_PAGE_CHAR_LIMIT = 15_000  # per crawled page, when sent to the model
CONTEXT_SITE_CHAR_BUDGET = 240_000  # all pages together (~60k tokens); overflow is reported, not silent
CONTEXT_MIN_PAGES_WARNING = 3

# Apify: renders JavaScript-only pages during onboarding (and fetches Reddit from Milestone 3)
APIFY_TOKEN = env("APIFY_TOKEN", default="")
APIFY_RENDER_ACTOR = env("APIFY_RENDER_ACTOR", default="apify/website-content-crawler")

# Reddit Agent
REDDIT_SOURCE = env("REDDIT_SOURCE", default="apify")  # "apify" | "fake" (local testing, no Apify spend)
APIFY_REDDIT_ACTOR = env("APIFY_REDDIT_ACTOR", default="harshmaur/reddit-scraper")
LLM_BATCH_POLL_SECONDS = env.int("LLM_BATCH_POLL_SECONDS", default=120)
LLM_BATCH_MAX_AGE_HOURS = 24

# Content policy packs (industry rules as data)
POLICY_PACKS_DIR = BASE_DIR / "policies"
