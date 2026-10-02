"""The mechanical half of docs/security-patterns.md.

These rules are simple enough to check on every test run, so a PR can't quietly break
them: which views are public, which calls are banned, where outbound HTTP may live, and
what the frontend may never do. The judgement calls (tenant scoping of each query, SSRF,
model-output effects) are for the /security-scan review; this file only guards the floor.
"""

import re
from pathlib import Path

import pytest
from django.conf import settings
from django.urls import URLPattern, URLResolver, get_resolver
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

BACKEND = Path(settings.BASE_DIR)
APP_ROOTS = ["apps", "llm", "providers", "config"]

# Keep in sync with the public-view table in docs/security-patterns.md §2.
PUBLIC_VIEWS = {
    "apps.core.views.CsrfView",
    "apps.core.views.LoginView",
    "apps.core.views.HealthView",
    "apps.core.views.WaitlistView",
    # Mounted only when DJANGO_API_DOCS is on, which prod defaults to off.
    "drf_spectacular.views.SpectacularAPIView",
    "drf_spectacular.views.SpectacularSwaggerView",
}
NO_AUTH_VIEWS = {
    "apps.core.views.HealthView",
    "apps.core.views.WaitlistView",
}


def _drf_views(patterns=None, prefix=""):
    for p in get_resolver().url_patterns if patterns is None else patterns:
        if isinstance(p, URLResolver):
            yield from _drf_views(p.url_patterns, prefix + str(p.pattern))
        elif isinstance(p, URLPattern):
            cls = getattr(p.callback, "cls", None)
            if cls is not None and issubclass(cls, APIView):
                yield prefix + str(p.pattern), cls


def _name(cls) -> str:
    return f"{cls.__module__}.{cls.__qualname__}"


def test_drf_views_are_found():
    assert len(list(_drf_views())) > 20


def test_only_listed_views_are_public():
    public = {
        _name(cls): route
        for route, cls in _drf_views()
        if not cls.permission_classes or AllowAny in cls.permission_classes
    }
    unexpected = {name: route for name, route in public.items() if name not in PUBLIC_VIEWS}
    assert unexpected == {}, (
        "These views are reachable without logging in. If that is intended, add them to the "
        "public-view table in docs/security-patterns.md §2 and to PUBLIC_VIEWS here."
    )


def test_only_listed_views_skip_authentication():
    no_auth = {_name(cls) for _, cls in _drf_views() if cls.authentication_classes == []}
    assert no_auth <= NO_AUTH_VIEWS, (
        "authentication_classes = [] also disables CSRF; only stateless public views may set it"
    )


# --- Application code ------------------------------------------------------------------

def app_files():
    for root in APP_ROOTS:
        for p in (BACKEND / root).rglob("*.py"):
            if {"tests", "migrations"} & set(p.parts):
                continue
            yield p


def _rel(p: Path) -> str:
    return str(p.relative_to(BACKEND))


# pattern -> why it's banned (docs/security-patterns.md §9)
BANNED_CALLS = {
    r"\byaml\.(unsafe_)?load\(": "use yaml.safe_load",
    r"^\s*(import|from)\s+(pickle|marshal|shelve)\b": "unsafe deserialization; use JSON",
    r"(?<![\w.])eval\(": "never eval data",
    r"(?<![\w.])exec\(": "never exec data",
    r"^\s*(import|from)\s+subprocess\b|\bos\.(system|popen)\(|shell=True": "no shelling out",
    r"\.raw\(|\.extra\(|\bRawSQL\(": "use the ORM",
    r"\bmark_safe\(|\bformat_html\(": "the API returns JSON, never HTML",
    r"corsheaders|CORS_ALLOW_ALL_ORIGINS": "no CORS by design (§3)",
}

# HealthView's `SELECT 1` is the only raw SQL.
RAW_CURSOR_ALLOWED = {"apps/core/views.py"}


@pytest.mark.parametrize("pattern", BANNED_CALLS, ids=list(BANNED_CALLS.values()))
def test_no_dangerous_calls_in_app_code(pattern):
    rx = re.compile(pattern, re.M)
    offenders = [_rel(p) for p in app_files() if rx.search(p.read_text())]
    assert offenders == [], f"{BANNED_CALLS[pattern]}: {offenders}"


def test_raw_cursor_only_in_health_check():
    offenders = []
    for p in app_files():
        if re.search(r"cursor\.execute", p.read_text()) and _rel(p) not in RAW_CURSOR_ALLOWED:
            offenders.append(_rel(p))
    assert offenders == []


HTTP_CLIENTS = re.compile(
    r"^\s*(import|from)\s+(httpx|requests|aiohttp|urllib3|urllib\.request|apify_client)\b", re.M
)


def test_outbound_http_only_in_providers():
    """SSRF rules live in providers/ (§6); a fetch anywhere else bypasses them."""
    offenders = [
        _rel(p) for p in app_files()
        if HTTP_CLIENTS.search(p.read_text()) and not _rel(p).startswith("providers/")
    ]
    assert offenders == []


HTTPX_CLIENT = re.compile(r"\bhttpx\.(Client|AsyncClient|HTTPTransport|get|post|request|stream)\(")


def test_httpx_clients_are_only_built_by_the_guarded_module():
    """Tenant-directed fetches must use `guarded_client`, which refuses non-public addresses
    (§6). A client built anywhere else would skip that check."""
    offenders = [
        _rel(p) for p in app_files()
        if HTTPX_CLIENT.search(p.read_text()) and _rel(p) != "providers/crawl/http.py"
    ]
    assert offenders == []


def test_celery_never_uses_pickle():
    assert getattr(settings, "CELERY_TASK_SERIALIZER", "json") == "json"
    assert "pickle" not in getattr(settings, "CELERY_ACCEPT_CONTENT", ["json"])


# --- Frontend --------------------------------------------------------------------------

FRONTEND = BACKEND.parent / "frontend"

FRONTEND_BANNED = {
    r"dangerouslySetInnerHTML": "React escapes by default; don't opt out",
    r"\.innerHTML\s*=|\.outerHTML\s*=": "write DOM through React",
    r"rehype-raw": "markdown must not render raw HTML",
    r"(?<![\w.])eval\(|new Function\(": "never eval data",
}


@pytest.mark.skipif(not (FRONTEND / "src").exists(), reason="frontend/ isn't mounted here")
@pytest.mark.parametrize("pattern", FRONTEND_BANNED, ids=list(FRONTEND_BANNED.values()))
def test_frontend_has_no_unsafe_html(pattern):
    rx = re.compile(pattern)
    files = [p for p in (FRONTEND / "src").rglob("*") if p.suffix in {".ts", ".tsx", ".js", ".jsx"}]
    files.append(FRONTEND / "package.json")
    offenders = [str(p.relative_to(FRONTEND)) for p in files if rx.search(p.read_text())]
    assert offenders == [], f"{FRONTEND_BANNED[pattern]}: {offenders}"
