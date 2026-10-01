# Luka security patterns

The security scan (`/security-scan`, in `.claude/skills/security-scan/`) checks every branch against this document. It describes how Luka is **meant** to handle security. Code that follows a pattern here is expected and is not a finding. Code that departs from one is a candidate finding, and the rubric in §13 grades it.

Keep this document true. When a PR adds a legitimate new trust boundary, update the matching section in the same PR. That includes a public view, an outbound fetch, an LLM tool, a new effect of model output, or a new third party that receives content. The mechanical rules are also enforced by `backend/tests/test_security_patterns.py`.

---

## 1. Trust boundaries

| Boundary | Untrusted side | Guarded by |
|---|---|---|
| Browser → DRF API | Every request, including logged-in ones (another tenant is also a logged-in user) | Session auth + CSRF, `IsAuthenticated`, `current_project()` scoping (§2–3) |
| Worker → internet | Any URL a user or a crawled page supplies | `providers/crawl/` URL rules (§6) |
| Text → LLM | Crawled pages, Reddit posts, user nudges and guidance, context docs derived from crawls | Prompt structure and a fixed allowlist of effects model output can have (§7) |
| Model output → database, config, spend | Everything a model returns | Pydantic schemas, a fixed set of effects, nothing published automatically (§7) |
| API → browser | Stored model output, crawled URLs, Reddit URLs | React escaping, http(s)-only URLs (§8) |
| Tenant → operator's wallet | Any setting that multiplies LLM or Apify calls | Limits enforced on the server (§11) |

Luka is multi-tenant: **users own projects, and every domain row hangs off a project.** The worst class of bug is one user reading or changing another user's project.

---

## 2. Authentication and tenancy

**Defaults** (`backend/config/settings/base.py`):
```python
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
}
```
Views inherit these. There is no public signup: an admin creates accounts in Django admin or with `manage.py bootstrap`.

**Public views: this is the complete list.** Anything not listed here is a finding. Each entry is also in `PUBLIC_VIEWS` in `test_security_patterns.py`.

| View | `permission_classes` | `authentication_classes = []` | Why |
|---|---|---|---|
| `apps.core.views.CsrfView` | `AllowAny` | no | Issues the CSRF cookie before login |
| `apps.core.views.LoginView` | `AllowAny` | no | Login |
| `apps.core.views.HealthView` | `AllowAny` | yes | Render health check; returns `{"ok": true}` only |
| `apps.core.views.WaitlistView` | `AllowAny` | yes | Landing-page form; `ScopedRateThrottle`; the same answer for new and repeat emails |
| `drf_spectacular` `SpectacularAPIView` / `SpectacularSwaggerView` | `AllowAny` | no | `/api/schema/`, `/api/docs/`. Mounted only when `DJANGO_API_DOCS` is on, which prod defaults to off (§12) |

**The tenant boundary is `current_project(request)`** (`apps/core/selection.py`). It resolves the project from the `X-Project-Id` header, then the session, then the user's first project, and **always filters by `owner=request.user`**. No view defines object-level permissions, so the queryset filter is the only control.

```python
# CORRECT: every project-scoped query goes through current_project
Draft.objects.filter(project=current_project(request))
get_object_or_404(BlogTopic, pk=pk, project=current_project(request))
get_object_or_404(AgentRun, pk=pk, project=current_project(request))

# CORRECT: project-level objects are scoped by owner
Project.objects.filter(owner=request.user)
get_object_or_404(Project, pk=pk, owner=request.user)

# CORRECT: one helper that every endpoint of a resource uses
def drafts_qs(request):
    return Draft.objects.filter(project=current_project(request))

# WRONG: unscoped lookup by an id taken from the request (CRITICAL)
Draft.objects.get(pk=pk)
AgentRun.objects.filter(pk=request.query_params["run"])
Project.objects.get(pk=request.data["project_id"])

# WRONG: trusting a project id from the body or query string instead of current_project
Draft.objects.filter(project_id=request.data["project"])
```

**Rules:**
- Serializers must not let a client set `project`, `owner` or other tenancy foreign keys. Set them on the server in `perform_create` / `save(project=...)`.
- A serializer that accepts the id of a related object must check that the object is in the caller's project. Examples are a `blog_topic` or a `source_reddit_post`.
- **Celery tasks** receive ids, never objects. They load the `AgentRun` by pk and take the project from `run.project`. Any other object is loaded scoped to that project, as in `Draft.objects.get(pk=..., project=run.project)`. A task must never act on a project other than its run's.
- **Every new endpoint needs a tenancy test** in `backend/tests/test_tenancy.py`: another user's object returns 404 and doesn't show up in the lists. The docstring there explains why: those tests are the only thing between two customers' inboxes.
- **Admin** (`/admin/`) is for the operator's superuser only. It shows every tenant, so no staff accounts are handed to customers.

---

## 3. Sessions, CSRF and CORS

- **Same origin, no CORS, on purpose.** The SPA reaches `/api/*` on its own origin: through Vite's proxy in dev, a Render rewrite or Caddy in prod. `django-cors-headers` is not installed.
  - Adding CORS middleware, `CORS_ALLOW_ALL_ORIGINS = True` or `CORS_ALLOW_CREDENTIALS` with a wildcard is **Critical**. Changing the deployment topology is a design decision to discuss, not something a PR does quietly.
- **CSRF middleware is on.** The frontend (`frontend/src/lib/api.ts`) reads the `csrftoken` cookie, or calls `GET /api/auth/csrf/`, and sends `X-CSRFToken` on every unsafe method.
- **No `csrf_exempt`** on an endpoint that uses a session, and no `authentication_classes = []` on a view that changes state for a user. Only the views in the §2 table skip authentication.
- **Cookies:** session cookie HttpOnly (Django default), SameSite=Lax (default), `SESSION_COOKIE_SECURE` and `CSRF_COOKIE_SECURE` in prod.
- `CSRF_TRUSTED_ORIGINS` comes from env plus `RENDER_EXTERNAL_HOSTNAME`. No wildcards.

---

## 4. Secrets

- **Every secret comes from the environment** through `django-environ` in `config/settings/*.py`. Code reads secrets from `settings`, never from `os.environ` spread around the codebase, and never as literals.
- **Expected secrets** (in `.env`, never in code):
  - `DJANGO_SECRET_KEY`
  - `DATABASE_URL`
  - `REDIS_URL`
  - `ANTHROPIC_API_KEY`
  - `APIFY_TOKEN`
  - `LANGSMITH_API_KEY`
  - `SENTRY_DSN`
  - `LUKA_ADMIN_PASSWORD`
- **Not secrets, and acceptable in the repo:**
  - `config/settings/test.py` (`SECRET_KEY="test"`, `ANTHROPIC_API_KEY="test-key"`)
  - the Dockerfile's build-time `DJANGO_SECRET_KEY=collectstatic-only`
  - the dev Postgres credentials `luka/luka` in `docker-compose.yml`
- **Never committed:** `.env` and `.env.*` (`.env.example` is the exception, and it holds names only). `.gitignore` and both `.dockerignore` files exclude them.
- **Render:** `DJANGO_SECRET_KEY` uses `generateValue: true`; other secrets use `sync: false`.
- **Never visible to the browser:** a secret, token or key must not appear in an API response, a `RunEvent`, a log line, a Sentry event or the frontend bundle. The frontend has no secrets. Vite only exposes `VITE_*` variables, so don't create one that holds a key.

```python
# CORRECT
client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
# WRONG (CRITICAL)
APIFY_TOKEN = "apify_api_..."
```

---

## 5. Input validation

- **Every request body goes through a DRF serializer**, and views read `serializer.validated_data`. There is currently no `request.data.get(...)` in any view; keep it that way.
- **Agent config** is merged with the stored config and validated by the agent's Pydantic `config_model` (`apps/*/config.py`). Errors come back through `apps.core.errors.validation_errors`. Every numeric field has bounds, and every list and string has a size limit.
- **Draft content** is validated per kind by the Pydantic models in `apps/inbox/content.py` inside `services.add_version`.
- **Query params** are parsed defensively. A bad value is a 400, or ignored, never a 500:
  ```python
  # CORRECT
  try:
      weeks = max(1, min(52, int(request.query_params.get("weeks", 8))))
  except ValueError:
      weeks = 8
  # WRONG: a non-numeric value raises ValueError → 500
  after = int(request.query_params["after"])
  ```
- **`JSONField` in a serializer is typed.** Use a `DictField` or a nested serializer and check the shape. An untyped JSONField that feeds `{**a, **b}` or indexing is a 500 waiting to happen.
- **URLs from users** use `URLField`. The server then restricts them to http(s) before they are fetched (§6) or rendered as a link (§8). Django's `URLField` also accepts `ftp`/`ftps`.
- **Choice-like strings** (agent type, doc kind, nudge) are checked against a registry or `ChoiceField`, never used directly as a lookup key or file path.

---

## 6. Outbound fetches and SSRF

Luka's worker fetches URLs that come from users, such as `website_url`, and from crawled pages: sitemap entries, links and redirects. **That makes the crawler an SSRF surface**, because the worker sits inside the deployment network.

- **Only `backend/providers/` makes outbound HTTP.** That means `httpx`, `urllib.request`, Apify clients and any future provider. The one exception is the Anthropic SDK in `backend/llm/`. Apps and pipelines call the provider interfaces. `test_security_patterns.py` enforces this.
- **Scheme:** http(s) only (`providers/crawl/urls.normalize`).
- **Host:** the crawler stays on the site being crawled (`same_site`), and that applies to **every** URL it fetches, not only page links:
  - sitemap URLs listed in `robots.txt`
  - child `<sitemap><loc>` entries
  - redirect targets, which have to be checked on each hop, not just followed
- **Address:** a user-supplied host must not resolve to a loopback, private (RFC 1918), link-local (`169.254.0.0/16`, including cloud metadata), CGNAT, multicast or unspecified address, or the IPv6 equivalents. The check runs on the resolved address, not only on the hostname string.
- **Size and time:** bounded timeouts (15s) and a byte cap enforced **while streaming**, not after `resp.content` has been read into memory.
- **Nothing fetched is echoed raw to the API.** Crawled text reaches users only after extraction, in context docs. Error bodies from fetched URLs are never returned.
- **Fetches that happen elsewhere:** `ApifyRenderer` sends only same-site URLs to Apify with `maxCrawlDepth: 0`, so Apify's servers do the fetch. `ApifyRedditSource` builds URLs on a fixed host (`www.reddit.com`), and any user part (the subreddit) is URL-encoded.

```python
# WRONG: fetching a URL a crawled page told us about, without re-checking the site
queue.extend(doc.child_sitemaps)          # could be http://169.254.169.254/...
# CORRECT
queue.extend(u for u in doc.child_sitemaps if same_site(u, root))
```

Severity: SSRF whose response a tenant can read back is **Critical**. That includes the text stored in `CrawledPage`, context docs, and `RunEvent` data such as an `HTTP <status>` skip reason. Blind SSRF is **High**.

---

## 7. LLM and prompt injection

Luka's prompts are full of text we don't control: crawled pages, Reddit posts and user nudges. We accept that a model can be *steered* by that text. What we control is **what a steered model can do.**

**Prompt construction:**
- Prompts are repo files, `backend/prompts/<task>/vN.md` (YAML frontmatter plus a Jinja body), loaded only through `llm.prompts`. Frontmatter uses `yaml.safe_load`.
- User and crawled data enter **only as Jinja variables**. No user string is ever compiled as a template: no `Environment.from_string(user_text)` and no `jinja2.Template(user_text)`. The only templates are repo files and the policy-pack YAML (`apps/policy/service.py`).
- Untrusted text goes inside explicit delimiters, such as `<page url="..." title="...">…</page>`, `<post>…</post>` or `<instruction>…</instruction>`. Attribute values are escaped so that a `"` or `>` in a title can't close the tag. Prompts tell the model that delimited content is data to analyse, not instructions.
- Crawled text goes into the system prompt only as the cached site block during onboarding. It is not presented as authoritative instructions.

**What model output may do.** This is an allowlist; anything else is a finding:

| Effect | Where | Guard |
|---|---|---|
| Write or replace a `Draft` / `DraftVersion` | agent pipelines, regenerate | Pydantic content schema; a human triages; nothing is published |
| Write `ContextDocument` content | onboarding, doc regenerate | Revision history; editable by a human |
| Set `project.name`, `product_summary`, append to `project.competitors` | onboarding | Only on the caller's project; URLs normalised to http(s) |
| Suggest a policy pack | onboarding | Only known pack ids; falls back to `general`; a user-chosen policy is never overwritten |
| Seed the Reddit agent's `subreddits` / `keywords` **only when they are empty** | onboarding | Pydantic `RedditAgentConfig`; tracked as a known concern (§14) |
| Score posts, flag compliance issues | reddit / lint | Stored fields only |
| Write an agent's learnings (`AgentLearnings.writing_md` / `selection_md`), which later drafting and scoring prompts read | `digest_feedback` run (`apps/feedback/`) | Only from the caller's project's feedback; third-party text in the digest input (post titles, draft excerpts) is escaped and delimited as data; shown, editable and rebuildable on the agent page; only shapes drafts and scores, which a human triages |

**Rules:**
- **No new side effects from model output without a human in the loop.** Examples: publishing, sending, changing schedules or `enabled`, raising limits, or calling a new external API. A new side effect is **High** unless a human confirms it in the UI.
- **Tools:** `VALID_TOOLS = {"web_search"}` (`llm/prompts.py`), enabled only in the competitors prompt, with `web_search_max_uses` set. Adding a tool, especially one that reaches our own systems or fetches arbitrary URLs from our infrastructure, needs this document updated and is reviewed as a new trust boundary.
- **Structured output is validated.** Model output is parsed with Pydantic (`model_validate_json`) and never `eval`'d or executed. It is not used as a URL, path, SQL, shell command or template without validation.
- **Model output shown in the UI** follows §8. Markdown is rendered without raw HTML, and links are http(s) only.

Reviewer note: "user content appears in a prompt" is **not** a finding on its own. That's how the product works. It becomes one when steered output reaches an effect outside the allowlist, or leaks another tenant's data (the context block is per project, so this shouldn't be possible).

---

## 8. Frontend XSS

- **React escapes output by default.** A plain `{value}` in JSX is safe.
- **No `dangerouslySetInnerHTML`, `innerHTML`, `eval` or `new Function`** in `frontend/src`. The test enforces this.
- **Markdown** goes through `components/markdown.tsx` (`react-markdown` + `remark-gfm`):
  - **no `rehype-raw`**, so raw HTML stays escaped
  - no `urlTransform` override that allows `javascript:`
  - context docs, blog bodies and anything model-written render through this component only
- **URLs from data** end up in `href={...}` or `window.open(...)`. They must be **http(s), checked on the server** before they reach the client. React warns about a `javascript:` href but still renders it. Examples are `RedditPost.url`, `posted_url`, `open_url`, `page.url` and `website_url`.
  - Validate at write time: a model validator, or a scheme check before `bulk_create`. `bulk_create` skips field validators.
  - Also validate at read time in the serializer when the data comes from a provider.
- **External links** use `target="_blank" rel="noopener noreferrer"`, or `window.open(url, "_blank", "noopener")`.
- **`localStorage`** holds UI preferences only, such as the theme. Never tokens or content.

---

## 9. Deserialization and dangerous calls

These are banned in application code (not tests or migrations). `test_security_patterns.py` enforces the list:

| Banned | Use instead |
|---|---|
| `yaml.load(`, `yaml.unsafe_load(` | `yaml.safe_load` |
| `pickle`, `marshal`, `shelve` | JSON |
| `eval(`, `exec(`, `compile(` on data | parsing and validation |
| `subprocess`, `os.system`, `os.popen`, `shell=True` | a provider or library call |
| `.raw(`, `.extra(`, `RawSQL`, `cursor.execute` (except `HealthView`'s `SELECT 1`) | the ORM |
| `mark_safe`, `format_html` with user data | DRF JSON responses (the API never returns HTML) |
| `Template(user_text)` / `from_string(user_text)` | repo templates with variables (§7) |

- **XML** (sitemaps) is parsed with `XMLParser(resolve_entities=False, no_network=True, huge_tree=False)`, which is XXE-safe. Any new XML parsing uses the same settings or `defusedxml`.
- **Celery** uses the default JSON serializer, and task arguments are ids and strings. Never switch to pickle.

---

## 10. Errors and data exposure

- **No tracebacks, exception strings with internals, SQL or file paths in API responses.**
  - DRF's `config.exceptions.exception_handler` logs 5xx errors and returns a generic body.
  - `DEBUG` is False in prod.
  - Run failures give the client a short summary. The traceback belongs in logs and Sentry, not in a serialized field.
- **Logging and Sentry:** follow CLAUDE.md, "Log identifiers, never content." `observability.py` sets `send_default_pii=False`, `max_request_body_size="never"` and no frame locals by default. Don't loosen any of those in a PR.
- **`RunEvent.data`** is ids, counts, scores, durations and costs only, never crawled text, draft bodies or post bodies. The UI shows it.
- **Third parties that receive content**, and are allowed to:
  - **Anthropic:** prompts
  - **Apify:** same-site URLs and Reddit search terms
  - **LangSmith:** prompt inputs and outputs, only when `LANGSMITH_TRACING` is on
  - **Sentry:** identifiers only

  Sending content anywhere new is a new trust boundary, so update this list.
- **Anti-enumeration:** the waitlist answers new and repeat emails the same way. `current_project` treats "not yours" like "doesn't exist". Keep that behaviour on new public or cross-object endpoints.

---

## 11. Spend abuse

The operator's `ANTHROPIC_API_KEY` and `APIFY_TOKEN` pay for **every** tenant. Any setting that multiplies calls is a way to spend someone else's money.

- **Every multiplier has a server-side bound**, in a serializer or Pydantic model:
  - `max_pages` (1–200)
  - `max_posts_per_run`
  - `posts_per_run`
  - `topics_per_run`
  - the number of subreddits and keywords (Reddit runs one search per pair)
  - `web_search_max_uses`
  - `max_tokens`
  - feedback digests: one active digest per project (rebuild returns 409 while one runs), new feedback waits `FEEDBACK_DIGEST_DELAY_SECONDS` so a burst is one call, at most 100 entries per digest, and at most 20 undigested entries passed to a drafting call
- **Schedules:** an agent cron must not be able to fire more often than a sensible minimum.
- **"Run now" and regenerate** refuse to start while a run of the same kind is active (the 409 path). Keep that guard on any new trigger.
- **Unbounded spend** that a single tenant can trigger is **High**. A bounded but generous limit is Medium at most.

---

## 12. Production settings

`config/settings/prod.py`:
- `DEBUG = False`
- `SECRET_KEY` required, with no default
- `ALLOWED_HOSTS` from env plus the Render host
- `SECURE_SSL_REDIRECT` (default on), `SECURE_PROXY_SSL_HEADER`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `SECURE_CONTENT_TYPE_NOSNIFF`
- `X_FRAME_OPTIONS = "DENY"` (Django default)
- API schema and Swagger off (`DJANGO_API_DOCS` defaults to false)

A PR must not:
- set `DEBUG = True`
- use `ALLOWED_HOSTS = ["*"]` outside `dev.py`
- turn off secure cookies or SSL redirect in prod
- publish `/api/schema/` in prod

---

## 13. Severity rubric

| Severity | Meaning | Luka examples |
|---|---|---|
| **CRITICAL** | Direct compromise of another tenant, the operator or the server | Unscoped lookup exposing another project's rows; a non-public view reachable anonymously; a committed secret; RCE (pickle, `yaml.load`, template from user text, `shell=True` with data); SSRF with a readable response; CORS wildcard with credentials; `DEBUG=True` in prod |
| **HIGH** | Exploitable with some precondition, or serious data exposure | Stored XSS (raw HTML in markdown, a `javascript:` URL in `href`/`window.open`); blind SSRF; model output causing an effect outside the §7 allowlist; tracebacks or secrets in API responses, `RunEvent`s or logs; a Celery task acting outside `run.project`; unbounded tenant-triggered spend; `csrf_exempt` on an authenticated write |
| **MEDIUM** | Needs unusual conditions, or weakens a defence | No throttle on login; missing security headers or CSP; a bad query param causing a 500; content sent to a new third party without an update here; a generous but bounded spend limit |
| **LOW** | Hardening, defence in depth | Insecure defaults outside prod; verbose non-secret log lines |

**Gate:** a PR may not be pushed with an open CRITICAL or HIGH finding that it introduced or made worse. MEDIUM and LOW are listed in the PR description and can be deferred. Deferred items that are accepted go into §14.

---

## 14. Known concerns (baseline register)

These are issues already in `main`. A branch scan does not report them again, **unless the PR makes one worse or touches the code involved without fixing it when the fix is small.** When one is fixed, delete it from this list in the same PR.

### High
1. **Crawler SSRF** (`providers/crawl/crawler.py`):
   - Sitemap URLs from `robots.txt` and child `<sitemap><loc>` entries are fetched without a `same_site` check.
   - Redirects are followed without re-checking scheme or host.
   - Nothing blocks private, loopback or link-local addresses for `website_url`.
2. **`RedditPost.url` scheme never validated.** It comes from Apify, is stored with `bulk_create` (which skips validators), and is rendered as `href` and returned as `open_url` for `window.open`.
3. **Tracebacks reach the client.** `agents/runs.py` stores `traceback.format_exc()` in `AgentRun.error`, which `AgentRunSerializer` and `agent_summary.last_error` expose.

### Medium
1. The login view has no throttle or lockout, and `AUTH_PASSWORD_VALIDATORS` isn't set.
2. The waitlist throttle is keyed on the whole `X-Forwarded-For` header (`NUM_PROXIES` unset) and uses per-process LocMem cache.
3. `SECURE_HSTS_SECONDS` defaults to 0. There's no CSP, and the SPA HTML served by Caddy or the Render static site has no security headers.
4. There's no minimum interval for agent cron; `* * * * *` is accepted (§11).
5. Model output seeds the Reddit agent's subreddits and keywords when they are empty. That drives future Apify spend (§7).
6. Crawled text sits in the system prompt with unescaped `url`/`title` attributes under "Treat these as ground truth."
7. Markdown renders remote images, which a model-written doc could use as a beacon.
8. Unvalidated query params cause 500s: `agents/views.py` `int(after)`, `agents/api.py` `int(min_score)` and `run_id`.
9. `EditSerializer.content` is an untyped `JSONField`, so a non-dict body raises `TypeError` and returns a 500.
10. The crawler's `MAX_BYTES` is checked after the whole body is downloaded.
11. `ApifyRedditSource` doesn't URL-encode the subreddit in the search URL. The host is fixed.

### Low
1. The base `SECRET_KEY` default is `dev-insecure-change-me`. Prod requires a real one.
2. `/admin/` has no IP allowlist, 2FA or separate throttle.
3. With LangSmith on, full prompt variables (crawled text, drafts) go to LangSmith.

---

## Scanner checklist

| Category | Check | Severity |
|---|---|---|
| **Tenancy** | Query or `get_object_or_404` on a project-scoped model without `project=current_project(request)` / `owner=request.user` | CRITICAL |
| **Tenancy** | Serializer lets the client set `project` / `owner`, or a related id not checked against the project | CRITICAL |
| **Tenancy** | Celery task loads objects without scoping to `run.project` | HIGH |
| **Tenancy** | New endpoint without a `test_tenancy.py` case | MEDIUM |
| **Auth** | `AllowAny` or `authentication_classes = []` on a view not in the §2 table | CRITICAL |
| **CSRF/CORS** | `csrf_exempt` on an authenticated write | HIGH |
| **CSRF/CORS** | `corsheaders`, `CORS_ALLOW_ALL_ORIGINS`, wildcard origins | CRITICAL |
| **Secrets** | Hardcoded key or token, or `.env` / credentials committed | CRITICAL |
| **Secrets** | Secret in a response, `RunEvent`, log line or `VITE_*` var | HIGH |
| **Input** | Body read without a serializer; `int()` on a query param without a guard; untyped `JSONField` | MEDIUM |
| **SSRF** | Outbound HTTP outside `providers/` / `llm/` | HIGH |
| **SSRF** | Fetching a URL without scheme, same-site and private-address checks | HIGH (CRITICAL if the response is readable) |
| **LLM** | Model output causing an effect outside the §7 allowlist | HIGH |
| **LLM** | New tool, or a user string compiled as a template | HIGH / CRITICAL |
| **XSS** | `dangerouslySetInnerHTML`, `rehype-raw`, a permissive `urlTransform` | HIGH |
| **XSS** | Data URL in `href` / `window.open` without a server-side http(s) check | HIGH |
| **Deserialization** | Anything in the §9 banned table | CRITICAL |
| **Errors** | Traceback or internal error text in an API response | HIGH |
| **Logging** | Content (page text, drafts, prompts) or PII in logs, Sentry or `RunEvent.data` | MEDIUM (HIGH if a secret) |
| **Spend** | A call multiplier with no server-side bound | HIGH |
| **Prod** | `DEBUG=True`, `ALLOWED_HOSTS=["*"]`, secure cookies or SSL redirect off in prod | CRITICAL |
