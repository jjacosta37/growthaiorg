from decimal import Decimal
from pathlib import Path

import environ

from config.observability import init_sentry

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
    "apps.feedback",
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

DATABASES = {"default": env.db("DATABASE_URL", default="postgres://luka:luka@localhost:5433/luka")}
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
    "EXCEPTION_HANDLER": "config.exceptions.exception_handler",
    # Only views that set a throttle_scope are throttled; today that is the public waitlist form.
    "DEFAULT_THROTTLE_RATES": {"waitlist": "10/hour"},
}
# The schema and Swagger UI are unauthenticated by drf-spectacular's default, so they are served
# only where that is wanted: on by default for local work and CI, off in prod (see prod.py).
API_DOCS_ENABLED = env.bool("DJANGO_API_DOCS", default=True)
SPECTACULAR_SETTINGS = {
    "TITLE": "Luka API",
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
# Models a user can pick for an agent's drafting calls (writer-tier prompts only). Projects store
# the key, never a model ID; which keys a project may use is decided in apps/agents/draft_models.py.
LLM_DRAFT_MODELS = {
    "sonnet": {"label": "Sonnet", "model": LLM_MODELS["writer"]},
    "opus": {"label": "Opus", "model": env("LLM_MODEL_OPUS", default="claude-opus-5-5")},
}
LLM_DRAFT_MODEL_DEFAULT = "sonnet"
# USD per million tokens. Cache writes (5m TTL) bill at 1.25x input, cache reads at 0.1x.
LLM_PRICING = {
    "claude-haiku-4-5-20251001": {"input": 1.00, "output": 5.00},
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00},
    "claude-sonnet-5": {"input": 2.00, "output": 10.00},
    "claude-opus-5-5": {"input": 4.00, "output": 20.00},
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
    "formatters": {
        # Render's log view shows one line per record with no metadata of its own, so the
        # line has to carry its own timestamp, level and source.
        "console": {
            "format": "%(asctime)s %(levelname)-7s %(name)s %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "console"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
    "loggers": {
        "trafilatura": {"level": "ERROR"},  # warns "discarding data" for every thin page
        "httpx": {"level": "WARNING"},
        # Django logs handled 5xx here; without this they are rendered but never printed.
        "django.request": {"level": "ERROR"},
    },
}

# Error reporting (Sentry). Unset DSN = disabled, which is the default everywhere but prod.
ENVIRONMENT = env("ENVIRONMENT", default="dev")
SENTRY_DSN = env("SENTRY_DSN", default="")
SENTRY_ENABLED = init_sentry(
    dsn=SENTRY_DSN,
    environment=ENVIRONMENT,
    # The deployed commit, for Sentry release tracking: Render sets RENDER_GIT_COMMIT on every
    # service, and the self-hosted compose file passes SENTRY_RELEASE.
    release=env("SENTRY_RELEASE", default=None) or env("RENDER_GIT_COMMIT", default=None),
    local_variables=env.bool("SENTRY_LOCAL_VARIABLES", default=False),
)

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
# Bounds on one Reddit search. The charge cap applies to pay-per-event actors, the item cap to
# pay-per-result ones (about $2 per 1,000 results), so a search is bounded under either model.
APIFY_REDDIT_MAX_CHARGE_USD = Decimal(env("APIFY_REDDIT_MAX_CHARGE_USD", default="1.00"))
APIFY_REDDIT_MAX_ITEMS = env.int("APIFY_REDDIT_MAX_ITEMS", default=500)

# Keyword search data for the Content Agent's topics
KEYWORD_SOURCE = env("KEYWORD_SOURCE", default="apify")  # "apify" | "fake" (local testing, no Apify spend)
APIFY_KEYWORD_ACTOR = env("APIFY_KEYWORD_ACTOR", default="keywordlab/keyword-search-volume")
KEYWORD_LOOKUPS_PER_RUN = 50
# $0.02 per run + $0.006 per keyword with data, so 50 keywords cost at most about $0.32.
APIFY_KEYWORD_MAX_CHARGE_USD = Decimal(env("APIFY_KEYWORD_MAX_CHARGE_USD", default="0.50"))
# GitHub App for opening blog posts as pull requests (docs/prds/0002-github-blog-prs.md).
# README has the registration steps. "fake" keeps an in-memory host for local dev and tests.
GIT_HOST = env("GIT_HOST", default="github")  # "github" | "fake"
GITHUB_APP_ID = env("GITHUB_APP_ID", default="")
GITHUB_APP_SLUG = env("GITHUB_APP_SLUG", default="")
GITHUB_APP_PRIVATE_KEY = env("GITHUB_APP_PRIVATE_KEY", default="").replace("\\n", "\n")
GITHUB_APP_CLIENT_ID = env("GITHUB_APP_CLIENT_ID", default="")
GITHUB_APP_CLIENT_SECRET = env("GITHUB_APP_CLIENT_SECRET", default="")
# Where users reach Luka; the PR description links back to the draft from here.
LUKA_APP_URL = env("LUKA_APP_URL", default="http://localhost:5173").rstrip("/")
LLM_BATCH_POLL_SECONDS = env.int("LLM_BATCH_POLL_SECONDS", default=120)
# Feedback is folded into the learnings digest this long after it arrives, so a burst costs one call.
FEEDBACK_DIGEST_DELAY_SECONDS = env.int("FEEDBACK_DIGEST_DELAY_SECONDS", default=60)
LLM_BATCH_MAX_AGE_HOURS = 24

# Content policy packs (industry rules as data)
POLICY_PACKS_DIR = BASE_DIR / "policies"
