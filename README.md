# Sift

An internal AI growth assistant for OpenWealth. Sift reads the website, writes context documents, and runs scheduled agents (Reddit, Content, X). The agents draft marketing content into an inbox for review, and nothing is posted automatically.

The architecture, data model and milestones are in [`CLAUDE.md`](CLAUDE.md).

**Status:** Phase 1 (backend). Milestones 1 (skeleton, auth, `llm/`), 2 (onboarding and context docs) 3 (inbox and Reddit Agent) and 4 (Content Agent) are done.

## API so far

| Endpoint | What it does |
|---|---|
| `POST /api/auth/login/`, `/logout/`, `GET /api/auth/me/`, `GET /api/auth/csrf/` | Session auth |
| `GET/PATCH /api/project/` | Project, including the editable competitors list |
| `GET/PATCH /api/policy/` | Content rules, author role, disclosure and blog disclaimer (used in every LLM call and by the compliance check) |
| `GET /api/policy/packs/`, `POST /api/policy/apply-pack/` `{pack}` | Industry policy packs (`backend/policies/*.yaml`) and switching to one |
| `GET /api/status/` | Sidebar status line: active runs and the current step |
| `POST /api/onboarding/start/` `{website_url, name?, max_pages?}` | Crawl the site and write all context docs (returns a run) |
| `POST /api/context/recrawl/` `{overwrite_edited?, max_pages?}` | Re-crawl and rewrite docs, keeping hand-edited docs unless told otherwise |
| `GET /api/context/docs/`, `GET/PATCH /api/context/docs/<kind>/` | Documents. PATCH saves your edit as a new revision |
| `POST /api/context/docs/<kind>/regenerate/`, `GET .../revisions/` | Regenerate one doc; revision history |
| `GET /api/context/pages/` | Crawled pages |
| `GET /api/runs/?kind=`, `/api/runs/<id>/`, `/api/runs/<id>/events/?after=<id>` | Run history and incremental progress events |
| `GET /api/inbox/counts/` | Sidebar badges: unread, and drafts ready per agent |
| `GET /api/drafts/?agent=&status=new\|posted\|dismissed&sort=newest\|score` | Inbox list |
| `GET /api/drafts/<id>/` | Detail: current content, copy text, open URL, source post, compliance flags, versions |
| `POST /api/drafts/<id>/edit/` `{content}` | Save your edit (the original AI version is kept) |
| `POST /api/drafts/<id>/regenerate/` `{nudge: shorter\|more_casual\|no_mention\|custom, instruction?}` | Regenerate (returns a run) |
| `POST /api/drafts/<id>/mark-posted/` `{posted_url?}`, `/dismiss/` `{reason, note?}`, `/restore/`, `/read/` | Triage actions |
| `GET /api/agents/`, `GET/PATCH /api/agents/<type>/` `{enabled?, cron?, config?}` | Agent status header and config (PATCH syncs the beat schedule) |
| `POST /api/agents/<type>/run-now/`, `GET /api/agents/<type>/runs/` | Manual trigger and run history |
| `GET /api/agents/reddit/skipped/?run=&min_score=` | Scanned-but-skipped posts with scores, for tuning the threshold |
| `GET /api/agents/content/topics/?status=`, `POST` `{title, angle?, target_keywords?, draft_now?}` | Blog topic backlog; request a specific topic (drafted right away by default) |
| `POST /api/agents/content/topics/<id>/draft/`, `/reject/` | Draft a backlog topic now, or reject it so it isn't proposed again |

Only one context run (onboarding, recrawl or regenerate) can be active at a time; another request returns 409.

## Local development

Requires Docker.

```bash
cp .env.example .env              # set ANTHROPIC_API_KEY, SIFT_ADMIN_USERNAME/PASSWORD
docker compose up --build         # web :8000, worker, beat, postgres, redis
```

A one-shot `migrate` service runs migrations and `manage.py bootstrap` before `web`, `worker` and `beat` start. `bootstrap` creates the admin user from `SIFT_ADMIN_*` and the default project. Then:

- API docs (Swagger): http://localhost:8000/api/docs/. Log in first via http://localhost:8000/admin/.
- Admin (LLM call log, batches, periodic tasks): http://localhost:8000/admin/
- Real API smoke test: `docker compose exec web python manage.py llm_smoke`

### Tests

All Anthropic calls are replaced with a fake client, so tests never hit the network.

```bash
docker compose run --rm web pytest
```

To run outside Docker, use Python 3.13 and Postgres on localhost:5433 (`docker compose up -d postgres`):

```bash
python -m venv .venv && .venv/bin/pip install -r backend/requirements-dev.txt
cd backend && ../.venv/bin/pytest
```

## Environment variables

| Variable | Purpose |
|---|---|
| `DJANGO_SECRET_KEY` | Required in prod |
| `DJANGO_DEBUG` | `true` for local dev |
| `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS` | Comma-separated |
| `DATABASE_URL` | Postgres URL |
| `REDIS_URL` | Celery broker |
| `SIFT_ADMIN_USERNAME`, `SIFT_ADMIN_PASSWORD`, `SIFT_ADMIN_EMAIL` | The single user, created by `bootstrap` |
| `ANTHROPIC_API_KEY` | Claude API |
| `LLM_MODEL_FAST`, `LLM_MODEL_WRITER` | Model IDs for cheap tasks and for writing |
| `LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT` | LangSmith tracing of every LLM call |
| `APIFY_TOKEN` | Renders JavaScript-only pages during onboarding; Reddit data (Milestone 3) |
| `APIFY_RENDER_ACTOR` | Browser renderer actor (default `apify/website-content-crawler`) |
| `REDDIT_SOURCE` | `apify` (default) or `fake` for local testing without Apify spend |
| `LLM_BATCH_POLL_SECONDS` | How often scheduled runs check their scoring batch (default 120) |
| `CRAWL_MAX_PAGES`, `CRAWL_DELAY_SECONDS` | Onboarding crawl limits (default 40 pages, 0.2s between requests) |

## Content policy (industry rules as data)

Nothing industry-specific is hardcoded. Each project has a **content policy**: its rules, who posts (author role), the disclosure line, and an optional blog disclaimer. The policy is rendered into the guardrails of every LLM call, and the compliance check tests drafts against it. It starts from a **policy pack**, a YAML file in `backend/policies/`. Onboarding suggests a pack from the website, and you can switch packs or edit any rule. To support a new industry, add a YAML file (`extends: general`).

## How LLM calls work

Everything goes through `backend/llm/`. Pipelines call `llm.complete("task.name", {...}, project=...)`.

- Prompts are versioned files: `backend/prompts/<task>/vN.md`, with frontmatter for model tier, max_tokens, effort, output schema and tools.
- Every call gets the guardrails and context documents as a cached system prefix.
- Structured outputs are validated with Pydantic, with one retry.
- Refusals and truncations are raised and logged, never parsed.
- Every call writes an `LLMCall` row with token counts, cache hits and cost, and is traced to LangSmith when enabled.

## Deploy

Render Blueprint (`render.yaml`) arrives in Milestone 6.
