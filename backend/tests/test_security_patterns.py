"""The mechanical half of docs/security-patterns.md.

These rules are simple enough to check on every test run, so a PR can't quietly break
them: which views are public, which calls are banned, where outbound HTTP may live, and
what the frontend may never do. The judgement calls (tenant scoping of each query, SSRF,
model-output effects) are for the /security-scan review; this file only guards the floor.
"""

import ast
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
    r"^\s*(import|from)\s+traceback\b": "tracebacks reach the log through exc_info, never a stored field (§10)",
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


# --- What a run shows the client (§10) ---------------------------------------------------
# Everything a reporter writes becomes a RunEvent (and run.stats) that the UI renders, so an
# exception's text, or a provider's `.error` string, must go through `public_message` first.

REPORTER_METHODS = {"step", "success", "warning", "error", "event"}
REPORTER_RECEIVER = re.compile(r"reporter|RunReporter\(")
# Helpers whose arguments are stored in a field the client reads.
CLIENT_VISIBLE_CALLS = {"fail_score"}


def _client_visible_call(node: ast.Call) -> bool:
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr in REPORTER_METHODS:
        return bool(REPORTER_RECEIVER.search(ast.unparse(func.value)))
    return isinstance(func, ast.Name) and func.id in CLIENT_VISIBLE_CALLS


def _leaks(expr: ast.AST, caught: set[str]) -> list[str]:
    """Raw exception or provider-error text inside `expr`, outside a `public_message(...)` call."""
    if isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name) and expr.func.id == "public_message":
        return []
    if isinstance(expr, ast.Attribute) and expr.attr == "call":
        return []  # LLMError.call is the LLMCall row, not text
    if isinstance(expr, ast.Name) and expr.id in caught:
        return [expr.id]
    if isinstance(expr, ast.Attribute) and expr.attr == "error":
        return [ast.unparse(expr)]
    return [leak for child in ast.iter_child_nodes(expr) for leak in _leaks(child, caught)]


def _run_text_leaks(tree: ast.AST) -> list[tuple[int, str]]:
    caught = {h.name for h in ast.walk(tree) if isinstance(h, ast.ExceptHandler) and h.name}
    found = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and _client_visible_call(node)):
            continue
        # `exc=` is the exception handed to the log and Sentry: the one place it belongs.
        values = [*node.args, *(k.value for k in node.keywords if k.arg != "exc")]
        found += [(node.lineno, leak) for value in values for leak in _leaks(value, caught)]
    return found


def test_run_messages_never_carry_exception_text():
    """`reporter.error(f"... {exc}")` put a provider's 401 body on the agent page; this keeps it from coming back."""
    offenders = [f"{_rel(p)}:{line} ({leak})" for p in app_files()
                 for line, leak in _run_text_leaks(ast.parse(p.read_text()))]
    assert offenders == [], (
        "Exception or provider-error text reaches the client through a run message. Pass the exception "
        "as exc= and show public_message(exc) instead (docs/security-patterns.md §10)."
    )


@pytest.mark.parametrize("source", [
    'try:\n    pass\nexcept Exception as exc:\n    reporter.error(f"failed: {exc}", exc=exc)',
    'try:\n    pass\nexcept Exception as e:\n    reporter.warning("failed: " + str(e))',
    'RunReporter(run).warning(f"lookup failed: {result.error}")',
    'try:\n    pass\nexcept Exception as exc:\n    fail_score(post, str(exc), exc.call)',
])
def test_the_run_text_check_catches_leaks(source):
    assert _run_text_leaks(ast.parse(source))


def test_the_run_text_check_allows_public_messages():
    source = (
        'try:\n    pass\nexcept Exception as exc:\n'
        '    reporter.error(f"failed: {public_message(exc)}", exc=exc)\n'
        '    fail_score(post, public_message(exc), exc.call)'
    )
    assert _run_text_leaks(ast.parse(source)) == []


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
