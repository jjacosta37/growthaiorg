# Luka security patterns

The security scan (`/security-scan`, in `.claude/skills/security-scan/`) checks every branch against this document. It describes how Luka is **meant** to handle security. Code that follows a pattern here is expected and is not a finding. Code that departs from one is a candidate finding, and the rubric in §13 grades it.

Keep this document true. When a PR adds a legitimate new trust boundary, update the matching section in the same PR. That includes a public view, an outbound fetch, an LLM tool, a new effect of model output, or a new third party that receives content. The mechanical rules are also enforced by `backend/tests/test_security_patterns.py`.

---

## 1. Where Luka runs, who attacks it, and the trust boundaries

### Deployment
Production is a **Mac mini on the operator's private home network**:
- Docker Compose runs web, worker, beat, Postgres and Redis on that one machine, behind Caddy.
- The host setup lives in the separate `mini-infra` repo; this repo builds the images.
- `render.yaml` is legacy and not deployed.

Hosting at home changes what a bug costs:

| Property of the host | Consequence for security |
|---|---|
| The server's "internal network" is a **home LAN** | SSRF reaches the router's admin page, NAS, printers and cameras, the operator's other computers, and services on the Mac itself. Docker Desktop containers reach the Mac through `host.docker.internal` and the LAN through NAT. None of those were built to face the internet. |
| Every outbound request leaves from the operator's **residential IP** | A server-side request to a host a tenant chooses shows that IP, and with it the operator's approximate location and ISP. It also attributes the traffic to the operator: abuse complaints go to their ISP, and blocklists flag their home connection. **Accepted for now** (§6, §14). |
| **One machine**, the operator's own | Compromising the app gives a foothold inside a home network, not a disposable cloud VM. Postgres, Redis and the Docker socket share the host. |

### Threat model
- **Assume the login page is on the internet and that anyone can get an account.** A public login, possibly with signup, is planned, perhaps while Luka is still on the mini.
- "Accounts are created by an admin" is true today, but it is **never** a mitigation. Don't lower a finding's severity because of it.
- The attacker to plan for is a normal, logged-in tenant. That tenant controls:
  - every field the API accepts
  - the website being crawled, and so every page, redirect, `robots.txt` and sitemap the crawler sees
  - the text that steers the models
- An anonymous internet user reaches only the §2 public views and whatever the host exposes (§12).

### Trust boundaries

| Boundary | Untrusted side | Guarded by |
|---|---|---|
| Browser → DRF API | Every request, including logged-in ones (another tenant is also a logged-in user) | Session auth + CSRF, `IsAuthenticated`, `current_project()` scoping (§2–3) |
| Worker → internet / home LAN | Any URL a user or a crawled page supplies | `providers/crawl/` URL and address rules (§6). Egress from the home IP is an accepted risk for now. |
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
Views inherit these. Today there is no public signup: an admin creates accounts in Django admin or with `manage.py bootstrap`. **Don't rely on that.** Rate every finding as if anyone can get an account (§1).

**Public views: this is the complete list.** Anything not listed here is a finding. Each entry is also in `PUBLIC_VIEWS` in `test_security_patterns.py`.

| View | `permission_classes` | `authentication_classes = []` | Why |
|---|---|---|---|
| `apps.core.views.CsrfView` | `AllowAny` | no | Issues the CSRF cookie before login |
| `apps.core.views.LoginView` | `AllowAny` | no | Login |
| `apps.core.views.HealthView` | `AllowAny` | yes | Container and proxy health check; returns `{"ok": true}` only |
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
- **Admin** (`/admin/`) is for the operator's superuser only. It shows every tenant, so no staff accounts are handed to customers. The host proxy routes `/admin/` to Django, so it is as reachable as the login page. Treat it as internet-facing (§14).

---

## 3. Sessions, CSRF and CORS

- **Same origin, no CORS, on purpose.** The SPA reaches `/api/*` on its own origin. In dev that's through Vite's proxy. In prod the host's Caddy routes `/api`, `/admin` and `/static` to Django, and the frontend container serves the SPA. `django-cors-headers` is not installed.
  - Adding CORS middleware, `CORS_ALLOW_ALL_ORIGINS = True` or `CORS_ALLOW_CREDENTIALS` with a wildcard is **Critical**. Changing the deployment topology is a design decision to discuss, not something a PR does quietly.
- **CSRF middleware is on.** The frontend (`frontend/src/lib/api.ts`) reads the `csrftoken` cookie, or calls `GET /api/auth/csrf/`, and sends `X-CSRFToken` on every unsafe method.
- **No `csrf_exempt`** on an endpoint that uses a session, and no `authentication_classes = []` on a view that changes state for a user. Only the views in the §2 table skip authentication.
- **Cookies:** session cookie HttpOnly (Django default), SameSite=Lax (default), `SESSION_COOKIE_SECURE` and `CSRF_COOKIE_SECURE` in prod.
- `CSRF_TRUSTED_ORIGINS` comes from env (`DJANGO_CSRF_TRUSTED_ORIGINS`). No wildcards. The `RENDER_EXTERNAL_HOSTNAME` branch in `prod.py` is legacy and inert on the mini.

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
- **Production secrets** live in env files on the Mac mini, managed by `mini-infra`, never in this repo. They're readable by anyone with access to that machine, so the machine's own account security is part of secret management.
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

Luka's worker fetches URLs that come from users, such as `website_url`, and from crawled pages: sitemap entries, links and redirects. Because the worker sits on the operator's home network and sends from the operator's home IP (§1), every such fetch carries two risks:
- **SSRF:** it can be pointed inward, at the LAN.
- **Egress identity:** when it goes outward, it shows who and where the operator is.

### Egress identity: an accepted risk, for now
**This is a real issue, and we've decided to live with it for now** (operator decision, 2026-10-02). The crawler fetches tenant-chosen sites directly from the mini. Any account holder can therefore learn the operator's home IP, and from it their approximate location and ISP, by crawling a site they control and reading its access logs. That traffic is also attributed to the operator's home connection. An egress proxy or relay would fix it, but it isn't worth the extra moving parts yet. The risk is listed under **Accepted risks** in §14, and it will be worked on later.

Until then:
- **A request from the home IP to a tenant-chosen host is still flagged, as MEDIUM, but fixing it is not required for now.** That covers the crawl and any future link preview, image fetch, URL check or webhook. Scans list each such fetch path in the PR's deferred Medium findings, so the exposure stays visible. Because it's Medium, it doesn't block the gate. Every such fetch must still follow the SSRF rules below, which are **not** relaxed.
- **Fixed provider APIs are called directly from the mini:** Anthropic, the Apify API, Sentry and LangSmith. Their hosts are fixed in code.
- **Don't add identifying details to tenant-directed requests.** No operator name, email, domain or contact URL in the user agent or headers. The IP is accepted; giving away more than the IP is not.
- **Don't build anything that relies on the home IP being secret.** A tunnel keeps it out of DNS, but a tenant can still learn it through the crawler.
- **Keep the eventual fix cheap.** Tenant-directed fetches go through `providers/crawl/` and its httpx client. When the egress fix lands, it can then be a single change, for example a proxy or relay URL from env that production requires.
- **Revisit when** signup opens to the public at scale, abuse or blocklisting of the home IP shows up, or Luka moves off the mini.

### SSRF: nothing tenant-directed may reach the home network
- **Only `backend/providers/` makes outbound HTTP.** That means `httpx`, `urllib.request`, Apify clients and any future provider. The one exception is the Anthropic SDK in `backend/llm/`. Apps and pipelines call the provider interfaces. `test_security_patterns.py` enforces this.
- **Scheme:** http(s) only (`providers/crawl/urls.normalize`).
- **Host:** the crawler stays on the site being crawled (`same_site`), and that applies to **every** URL it fetches, not only page links:
  - sitemap URLs listed in `robots.txt`
  - child `<sitemap><loc>` entries
  - redirect targets, which have to be checked on each hop, not just followed
- **Address:** a user-supplied host must not resolve to any of these:
  - loopback, private (RFC 1918) or link-local (`169.254.0.0/16`) addresses
  - CGNAT, multicast, reserved or unspecified addresses
  - the IPv6 equivalents, including IPv4-mapped forms

  On the mini this list covers the home LAN, the Mac's own services (`host.docker.internal` resolves to a private address) and the Docker network. The check runs on the **resolved** address before every request, including each redirect hop, not only on the hostname string. That catches a public name that resolves to `192.168.x.x`.
- **Size and time:** bounded timeouts (15s) and a byte cap enforced **while streaming**, not after `resp.content` has been read into memory.
- **Nothing fetched is echoed raw to the API.** Crawled text reaches users only after extraction, in context docs. Error bodies from fetched URLs are never returned.
- **Nothing fetched reports a map of the network back.** Skip reasons a tenant can see in `RunEvent` data say "skipped" or "unreachable". They don't give HTTP status codes for hosts the crawler shouldn't have been fetching, because those turn the crawler into a LAN port scanner.
- **Fetches that happen elsewhere:**
  - `ApifyRenderer` must send only same-site URLs to Apify, with `maxCrawlDepth: 0`, so Apify's servers do the fetch. Today it also forwards off-site redirect targets (§14).
  - `ApifyRedditSource` builds URLs on a fixed host (`www.reddit.com`), and any user part (the subreddit) is URL-encoded.

```python
# WRONG: fetching a URL a crawled page told us about, without re-checking the site
queue.extend(doc.child_sitemaps)          # could be http://169.254.169.254/...
# CORRECT
queue.extend(u for u in doc.child_sitemaps if same_site(u, root))
```

Severity: SSRF whose response a tenant can read back is **Critical**. That includes the text stored in `CrawledPage`, context docs, and `RunEvent` data such as an `HTTP <status>` skip reason. On a home network the readable targets are real: router and NAS admin pages are HTML. Blind SSRF is **High**.

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
- **Tools:** `VALID_TOOLS = {"web_search"}` (`llm/prompts.py`), enabled only in the competitors prompt, with `web_search_max_uses` set. Adding a tool, especially one that reaches our own systems or fetches arbitrary URLs from the mini (the home network and the home IP, §6), needs this document updated and is reviewed as a new trust boundary.
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
  - **An egress proxy or relay, if one is added later (§6):** the URLs the crawler fetches and the responses that come back

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

## 12. Production settings and host exposure

### What the mini exposes
- **Only the host proxy (Caddy) is reachable from outside the machine.** Django/gunicorn, the frontend container, Postgres, Redis and Celery are not published on the host's network interfaces:
  - in the production compose, no `ports:` for them, or bound to `127.0.0.1` at most
  - reachable only on the internal Docker network

  The dev `docker-compose.yml` publishes ports 8000, 5173 and 5433; it's for a developer's machine, never production.
- **Internet exposure goes through one deliberate path** chosen in `mini-infra`, such as a tunnel or one forwarded port to Caddy. Prefer a tunnel: it doesn't publish the home IP in DNS. A tenant can still learn the IP through the crawler (an accepted risk, §6), so the tunnel limits exposure; it doesn't make the IP secret.
- **TLS ends at the edge** (the tunnel or Caddy). `SECURE_PROXY_SSL_HEADER` trusts `X-Forwarded-Proto` only because the host proxy sets it. The proxy must overwrite, not pass through, a client-supplied `X-Forwarded-For` / `X-Forwarded-Proto`.
- **The Docker socket is never mounted** into an app container.
- **Containers stay on their own network.** None runs with `network_mode: host`, and none is privileged.
- **The SPA's HTML** should carry the same security headers as the API: CSP, `X-Frame-Options`, `nosniff`, `Referrer-Policy`. Today `frontend/Caddyfile.prod` sets only cache headers (§14).

### `config/settings/prod.py`
- `DEBUG = False`
- `SECRET_KEY` required, with no default
- `ALLOWED_HOSTS` from env (the `RENDER_EXTERNAL_HOSTNAME` branch is legacy)
- `SECURE_SSL_REDIRECT` (default on), `SECURE_PROXY_SSL_HEADER`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `SECURE_CONTENT_TYPE_NOSNIFF`
- `X_FRAME_OPTIONS = "DENY"` (Django default)
- API schema and Swagger off (`DJANGO_API_DOCS` defaults to false)

A PR must not:
- set `DEBUG = True`
- use `ALLOWED_HOSTS = ["*"]` outside `dev.py`
- turn off secure cookies or SSL redirect in prod
- publish `/api/schema/` in prod
- publish a backing service's port, mount the Docker socket, or use host networking in a production image or compose snippet

---

## 13. Severity rubric

| Severity | Meaning | Luka examples |
|---|---|---|
| **CRITICAL** | Direct compromise of another tenant, the operator, the server or the home network | Unscoped lookup exposing another project's rows; a non-public view reachable anonymously; a committed secret; RCE (pickle, `yaml.load`, template from user text, `shell=True` with data); SSRF with a readable response (LAN pages, the Mac's services); Postgres or Redis published beyond the host; the Docker socket mounted in a container; CORS wildcard with credentials; `DEBUG=True` in prod |
| **HIGH** | Exploitable with some precondition, or serious data exposure | Stored XSS (raw HTML in markdown, a `javascript:` URL in `href`/`window.open`); blind SSRF or a LAN port/status oracle; model output causing an effect outside the §7 allowlist; tracebacks or secrets in API responses, `RunEvent`s or logs; a Celery task acting outside `run.project`; unbounded tenant-triggered spend; `csrf_exempt` on an authenticated write |
| **MEDIUM** | Needs unusual conditions, or weakens a defence | No throttle on login; missing security headers or CSP; a bad query param causing a 500; content sent to a new third party without an update here; a generous but bounded spend limit; a server request to a tenant-chosen host from the home IP (accepted risk, §6) |
| **LOW** | Hardening, defence in depth | Insecure defaults outside prod; verbose non-secret log lines |

**Grade with the §1 threat model.** Any account may be hostile, and the operator's home network sits behind the server. "Only invited users can do this" never lowers a severity.

**Gate:** a PR may not be pushed with an open CRITICAL or HIGH finding that it introduced or made worse. MEDIUM and LOW are listed in the PR description and can be deferred. Deferred items that are accepted go into §14.

---

## 14. Known concerns (baseline register)

These are issues already in `main`. A branch scan does not report them again, **unless the PR makes one worse or touches the code involved without fixing it when the fix is small.** When one is fixed, delete it from this list in the same PR.

### Critical
1. **Crawler SSRF into the home network** (`providers/crawl/crawler.py`). Regraded from High after the 2026-09-30 audit, and the move to the mini makes the targets real.
   - **Entry points:**
     - Nothing checks `website_url`'s address, so `http://192.168.1.1/` or `http://host.docker.internal:…` is accepted (it comes from `StartOnboardingSerializer` or `PATCH /api/project`).
     - `follow_redirects=True` follows an on-site redirect to any host without re-checking it.
     - Sitemap URLs from `robots.txt` and child `<sitemap><loc>` entries are fetched without a `same_site` check.
   - **Read-back channels:**
     - `RunEvent` skip reasons (`HTTP <status>`, `not HTML`, `HTTP error`) work as a LAN port and status scanner.
     - Internal HTML page titles appear in `/api/context/pages/`.
     - Page text reaches the context docs.
     - Off-site redirect targets are also sent to Apify (`crawler.py:144`).

### High
1. **Unbounded Reddit/Apify spend** (`apps/reddit/config.py:7-8`).
   - `subreddits` and `keywords` have no count, length or format limit.
   - Apify start URLs = subreddits × keyword queries, with at least 5 results per URL (`providers/reddit/apify.py:109`), and nothing caps total items or charge.
   - Each run is limited only by the 15-minute actor timeout, and runs repeat through run-now or cron (Medium 4).
2. **`RedditPost.url` scheme never validated.** It comes from Apify, is stored with `bulk_create` (which skips validators), and is rendered as `href` and returned as `open_url` for `window.open`.
3. **Internal error text reaches the client:**
   - `agents/runs.py` stores `traceback.format_exc()` in `AgentRun.error`, which `AgentRunSerializer` and `agent_summary.last_error` expose.
   - The same goes for the `"Failed: {exc}"` `RunEvent` (`runs.py:137`).
   - It also goes for `score_error` in the skipped-posts API (`agents/api.py:138`).

### Medium
1. The login view has no throttle or lockout, and `AUTH_PASSWORD_VALIDATORS` isn't set. With a public login page this is the first thing to fix after the Criticals and Highs.
2. **Login CSRF** (`apps/core/views.py` `LoginView`). DRF exempts unauthenticated POSTs from CSRF, and `FormParser` is enabled. A cross-site form can sign a visitor into an attacker's account, and whatever the visitor then enters ends up there. It was Low while accounts were invite-only; the §1 threat model raises it.
3. `/admin/` is reachable through the host proxy, with no IP allowlist, 2FA or separate throttle. Restrict it to the private network or a VPN, or put it behind its own auth.
4. There's no minimum interval for agent cron; `* * * * *` is accepted (§11).
5. Model output seeds the Reddit agent's subreddits and keywords when they are empty. That drives future Apify spend (§7), and the seeded values skip `RedditAgentConfig` validation.
6. **No size caps on tenant text rendered into every LLM call:**
   - policy rules and `blog_disclaimer` (`apps/policy/views.py`)
   - context-doc `content_md` (`apps/context/serializers.py`)
   - `competitors` (`apps/core/serializers.py`)

   This is a bounded spend multiplier.
7. `SECURE_HSTS_SECONDS` defaults to 0. There's no CSP, and `frontend/Caddyfile.prod` adds no security headers to the SPA's HTML (§12).
8. The waitlist throttle is keyed on the whole `X-Forwarded-For` header (`NUM_PROXIES` unset) and uses per-process LocMem cache.
9. Crawled text sits in the system prompt with unescaped `url`/`title` attributes under "Treat these as ground truth."
10. Markdown renders remote images, which a model-written doc could use as a beacon. That leaks the *viewer's* IP to whoever controls the image URL.
11. **Unvalidated input causes 500s:**
    - query params: `agents/views.py` `int(after)`, `agents/api.py` `int(min_score)` and `run_id`
    - untyped `JSONField`s: `EditSerializer.content` and `BlogTopic.target_keywords` via `RequestTopicSerializer`
12. The crawler's `MAX_BYTES` is checked after the whole body is downloaded.
13. **Missing tenancy tests.** `tests/test_tenancy.py` has no cases for:
    - skipped posts
    - policy (GET, PATCH, apply-pack)
    - context pages, revisions and regenerate
    - topic draft
    - agent runs and run-now

    The code is scoped correctly today.

### Low
1. The base `SECRET_KEY` default is `dev-insecure-change-me`. Prod requires a real one.
2. With LangSmith on, full prompt variables (crawled text, drafts) go to LangSmith.
3. The number of X items and blog topics saved follows the model's output, not `posts_per_run` / `topics_per_run` (`apps/xagent/pipeline.py`, `apps/content/pipeline.py`). This is bounded by `max_tokens`.
4. `ApifyRedditSource` doesn't URL-encode the subreddit in the search URL. The host is fixed. High 1's format check would close this.

### Accepted risks
These are real issues that the operator has decided to live with for now. Scans still **flag them, at the severity given here, but fixing them is not required**, and the gate doesn't block on them. A scan reports an accepted risk when a PR touches or adds to it, and lists it under the deferred findings. The risks stay listed until they're fixed. Making one meaningfully worse is a separate, normal finding: for example, adding operator-identifying headers.

1. **MEDIUM: the home IP is visible to tenants** (accepted 2026-10-02; §6). The crawler fetches tenant-chosen sites directly from the mini, with a `LukaBot/0.1` user agent. Any account holder can learn the operator's home IP, approximate location and ISP from their own server's logs. The crawl traffic is also attributed to the home connection.
   - **Why accepted:** an egress proxy or Cloudflare Worker relay isn't worth the added complexity yet, and the impact is disclosure of the IP, not access.
   - **Planned fix:** route tenant-directed fetches through an egress proxy or relay, required in production.
   - **Revisit when:** signup opens publicly at scale, the home IP gets abuse reports or blocklisted, or Luka moves off the mini.

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
| **SSRF** | Fetching a URL without scheme, same-site and resolved private-address checks (on every redirect hop) | HIGH (CRITICAL if the response is readable) |
| **Egress** | Server request to a tenant- or page-chosen host from the home IP (accepted risk: flag it, fixing not required for now, §6) | MEDIUM |
| **Egress** | Tenant-directed fetch outside `providers/crawl/`'s client, so the eventual egress fix wouldn't cover it (§6) | MEDIUM |
| **Egress** | Operator-identifying details (name, email, domain) in the user agent or headers of tenant-directed requests | MEDIUM |
| **Host** | Production compose or image publishes Postgres, Redis, Django or Celery ports; mounts the Docker socket; uses host networking or privileged mode | CRITICAL |
| **Host** | Internet exposure that bypasses the host proxy, or the proxy passing through client `X-Forwarded-*` headers | HIGH |
| **LLM** | Model output causing an effect outside the §7 allowlist | HIGH |
| **LLM** | New tool, or a user string compiled as a template | HIGH / CRITICAL |
| **XSS** | `dangerouslySetInnerHTML`, `rehype-raw`, a permissive `urlTransform` | HIGH |
| **XSS** | Data URL in `href` / `window.open` without a server-side http(s) check | HIGH |
| **Deserialization** | Anything in the §9 banned table | CRITICAL |
| **Errors** | Traceback or internal error text in an API response | HIGH |
| **Logging** | Content (page text, drafts, prompts) or PII in logs, Sentry or `RunEvent.data` | MEDIUM (HIGH if a secret) |
| **Spend** | A call multiplier with no server-side bound | HIGH |
| **Prod** | `DEBUG=True`, `ALLOWED_HOSTS=["*"]`, secure cookies or SSL redirect off in prod | CRITICAL |
