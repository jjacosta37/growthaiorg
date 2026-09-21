# Helmly

An AI growth assistant for a company's marketing. Helmly reads the company's website, writes context documents, and runs scheduled agents (Reddit, Content, X). The agents draft marketing content into an inbox for review, and nothing is posted automatically.

**New here? Read [`docs/backend-guide.md`](docs/backend-guide.md)**, which covers the structure, data model and main flows with diagrams. Decisions and conventions are in [`CLAUDE.md`](CLAUDE.md).

**Status:** Phase 1 (backend) and Phase 2 (frontend) are built: the Vite app covers login, onboarding, inbox and detail panes, agent pages, context, settings and stats.

## API so far

| Endpoint | What it does |
|---|---|
| `POST /api/auth/login/`, `/logout/`, `GET /api/auth/me/`, `GET /api/auth/csrf/` | Session auth |
| `GET/PATCH /api/project/` | The caller's current project, including the editable competitors list |
| `GET/POST /api/projects/`, `POST /api/projects/<id>/select/`, `DELETE /api/projects/<id>/` | The caller's projects: list, create, switch, delete |
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
| `GET /api/stats/?weeks=8` | Weekly drafts per agent (generated, posted, dismissed), dismiss reasons, LLM and Apify spend, cache hit rate |
| `GET /api/health/` | Public health check (app and database) |
| `GET /api/agents/content/topics/?status=`, `POST` `{title, angle?, target_keywords?, draft_now?}` | Blog topic backlog; request a specific topic (drafted right away by default) |
| `POST /api/agents/content/topics/<id>/draft/`, `/reject/` | Draft a backlog topic now, or reject it so it isn't proposed again |

The X Agent has no endpoints of its own: configure it with `PATCH /api/agents/x/` `{config: {posts_per_run, formats, max_thread_posts, char_limit, recent_window, guidance}}`, and its drafts appear in the inbox as `x_post` or `x_thread`. Their `open_url` opens X's compose page with the first post pre-filled.

Only one context run (onboarding, recrawl or regenerate) can be active at a time; another request returns 409.

## Local development

Requires Docker.

```bash
cp .env.example .env              # set ANTHROPIC_API_KEY, HELMLY_ADMIN_USERNAME/PASSWORD
docker compose up --build         # app :5173, api :8000, worker, beat, postgres, redis
```

A one-shot `migrate` service runs migrations and `manage.py bootstrap` before `web`, `worker` and `beat` start. `bootstrap` creates the admin user from `HELMLY_ADMIN_*` and the default project. Then:

- Admin (LLM call log, batches, periodic tasks): http://localhost:8000/admin/
- The app: http://localhost:5173
- API docs (Swagger): http://localhost:8000/api/docs/. Log in first via http://localhost:8000/admin/.
  These pages are unauthenticated, so prod doesn't serve them; set `DJANGO_API_DOCS=true` to enable them on a staging service.
- Real API smoke test: `docker compose exec web python manage.py llm_smoke`

<details>
<summary>Upgrading a database created before the Sift → Helmly rename</summary>

The Postgres role and database were renamed from `sift` to `helmly`. `POSTGRES_*` only applies when the volume is first initialised, so an existing volume still has the old role and `migrate` fails with `password authentication failed for user "helmly"`.

Either start fresh (`docker compose down -v`, which **deletes local data**), or rename in place and keep it:

```bash
docker compose up -d postgres
docker compose exec -T postgres psql -U sift -d postgres <<'SQL'
ALTER DATABASE sift RENAME TO helmly;
CREATE ROLE helmly SUPERUSER LOGIN PASSWORD 'helmly';
ALTER DATABASE helmly OWNER TO helmly;
SQL
docker compose exec -T postgres psql -U helmly -d helmly <<'SQL'
DO $$
DECLARE r record;
BEGIN
  EXECUTE 'ALTER SCHEMA public OWNER TO helmly';
  FOR r IN SELECT tablename FROM pg_tables WHERE schemaname='public' LOOP
    EXECUTE format('ALTER TABLE public.%I OWNER TO helmly', r.tablename);
  END LOOP;
  FOR r IN SELECT sequencename FROM pg_sequences WHERE schemaname='public' LOOP
    EXECUTE format('ALTER SEQUENCE public.%I OWNER TO helmly', r.sequencename);
  END LOOP;
END $$;
SQL
```

The old `sift` role stays behind: it is Postgres's bootstrap superuser and owns pinned system catalogs, so it can't be dropped. Nothing uses it.

Also update `.env`: `HELMLY_ADMIN_*` (was `SIFT_ADMIN_*`) and `DATABASE_URL=postgres://helmly:helmly@localhost:5433/helmly`.

On Render, the Blueprint services were renamed too (`sift-web` → `helmly-web`, and so on), so a redeploy creates new services and prompts for the secrets again.
</details>

### Frontend

Vite + React + TypeScript, in `frontend/`. `docker compose up` runs it, or run it directly:

```bash
cd frontend && npm install && npm run dev
```

The dev server proxies `/api` to the backend, so the browser sees a single origin and
Django's `SameSite=Lax` session cookie works without CORS. Production does the same thing
through the Render static site's `/api` rewrite, so dev and production behave alike. Point
the proxy somewhere else with `VITE_API_TARGET`.

```bash
npm run test        # vitest: formatting, cron phrasing, API error mapping
npm run lint        # tsc --noEmit
npm run build       # production bundle into dist/
npm run gen:types   # regenerate src/lib/schema.d.ts from /api/schema/
```

Styling is CSS custom properties from `src/styles/tokens.css` (the design handoff's token
file, unmodified). Components live in `src/components/`, screens in `src/features/`.

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
| `HELMLY_ADMIN_USERNAME`, `HELMLY_ADMIN_PASSWORD`, `HELMLY_ADMIN_EMAIL` | The first admin user and their project, created by `bootstrap`. Add more users in Django admin. |
| `ANTHROPIC_API_KEY` | Claude API |
| `LLM_MODEL_FAST`, `LLM_MODEL_WRITER` | Model IDs for cheap tasks and for writing |
| `LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT` | LangSmith tracing of every LLM call |
| `APIFY_TOKEN` | Renders JavaScript-only pages during onboarding; Reddit data (Milestone 3) |
| `APIFY_RENDER_ACTOR` | Browser renderer actor (default `apify/website-content-crawler`) |
| `REDDIT_SOURCE` | `apify` (default) or `fake` for local testing without Apify spend |
| `LLM_BATCH_POLL_SECONDS` | How often scheduled runs check their scoring batch (default 120) |
| `CRAWL_MAX_PAGES`, `CRAWL_DELAY_SECONDS` | Onboarding crawl limits (default 40 pages, 0.2s between requests) |
| `SENTRY_DSN` | Error reporting. Blank (the default) disables it entirely |
| `ENVIRONMENT` | Tags reported errors (`dev`, `production`) |
| `SENTRY_LOCAL_VARIABLES` | Include frame locals in tracebacks. Off by default: locals can hold crawled page text and draft bodies |
| `LOG_LEVEL` | Root logger level (default `INFO`) |

## Error reporting

Unhandled exceptions — in a view, a Celery task, or an agent pipeline — go to Sentry when
`SENTRY_DSN` is set. Sentry's free Developer plan (5k errors/month, 1 user, unlimited
projects) is enough for one deployment.

- Errors only: `traces_sample_rate` is 0, and performance monitoring is off. LangSmith
  covers the LLM-side timing.
- Pipeline failures are tagged `agent_run_id`, `kind`, `trigger` and `project_id`, so an
  issue points straight at a run. The run's `RunEvent` trail rides along as breadcrumbs.
- A failing run is *not* re-raised — `AgentRun.status` is what the UI reads, and beat calls
  the agent task synchronously. `AgentRun.error` holds the full traceback for the UI, and
  Sentry gets the same exception.
- Nothing is sent without a DSN, so tests and local runs stay offline. Privacy settings are
  in `backend/config/observability.py`: no PII, no request bodies, no frame locals.

## Content policy (industry rules as data)

Nothing industry-specific is hardcoded. Each project has a **content policy**: its rules, who posts (author role), the disclosure line, and an optional blog disclaimer. The policy is rendered into the guardrails of every LLM call, and the compliance check tests drafts against it. It starts from a **policy pack**, a YAML file in `backend/policies/`. Onboarding suggests a pack from the website, and you can switch packs or edit any rule. To support a new industry, add a YAML file (`extends: general`).

## How LLM calls work

Everything goes through `backend/llm/`. Pipelines call `llm.complete("task.name", {...}, project=...)`.

- Prompts are versioned files: `backend/prompts/<task>/vN.md`, with frontmatter for model tier, max_tokens, effort, output schema and tools.
- Every call gets the guardrails and context documents as a cached system prefix.
- Structured outputs are validated with Pydantic, with one retry.
- Refusals and truncations are raised and logged, never parsed.
- Every call writes an `LLMCall` row with token counts, cache hits and cost, and is traced to LangSmith when enabled.

## Deploy (Render)

`render.yaml` is a Render Blueprint. It defines the web service (gunicorn), a Celery worker, Celery beat, managed Postgres and Key Value (Redis). It validates against Render's published schema. The frontend static site is added in Phase 2.

1. Push the repo to GitHub, and merge the branch you want to deploy.
2. In Render: **New → Blueprint**, then pick the repo and branch. Render prompts once for each secret on `helmly-web`:
   - `ANTHROPIC_API_KEY`, `APIFY_TOKEN`, and optionally `LANGSMITH_API_KEY` (set `LANGSMITH_TRACING=true` in the `helmly-shared` group to turn tracing on)
   - `HELMLY_ADMIN_USERNAME`, `HELMLY_ADMIN_PASSWORD`, `HELMLY_ADMIN_EMAIL`, for the single admin user
   - `SENTRY_DSN` on the `helmly-shared` group, so web, worker and beat all report into one
     project. Leave it blank to deploy with error reporting off.

   `helmly-worker` and `helmly-beat` read those same secrets from `helmly-web`, and `DJANGO_SECRET_KEY` is generated.
3. Every deploy runs `migrate` and `bootstrap` (idempotent) before the new version goes live. The health check is `/api/health/`.
4. Verify:
   - `https://<helmly-web host>/api/health/` returns `{"ok": true}`
   - you can log in at `/admin/`
   - in the Render shell for `helmly-web`, `python manage.py llm_smoke` makes one cheap real call
5. Onboard with `POST /api/onboarding/start/`, then enable agents with `PATCH /api/agents/<type>/` `{"enabled": true}`. Beat picks up schedule changes without a restart.
6. Once HTTPS is confirmed working, set `DJANGO_HSTS_SECONDS` (for example `31536000`) on `helmly-web`. Don't set it before then: browsers cache HSTS.

Notes:
- **Plans:** the Blueprint uses small instance types (`0.5c-512mb` services, `0.1c-256mb` Postgres, `256mb` Key Value). Background workers and `preDeployCommand` need paid plans. See Render's pricing page for current costs.
- **Beat:** run exactly **one** `helmly-beat` instance, or scheduled runs fire twice.
- **Redis:** Key Value uses `noeviction`, because it's the Celery broker and queued tasks must never be dropped.
