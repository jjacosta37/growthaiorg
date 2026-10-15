# Luka

An AI growth assistant for a company's marketing. Luka reads the company's website, writes context documents, and runs scheduled agents (Reddit, Content, X). The agents draft marketing content into an inbox for review, and nothing is posted automatically.

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
cp .env.example .env              # set ANTHROPIC_API_KEY, LUKA_ADMIN_USERNAME/PASSWORD
docker compose up --build         # app :5173, api :8000, worker, beat, postgres, redis
```

A one-shot `migrate` service runs migrations and `manage.py bootstrap` before `web`, `worker` and `beat` start. `bootstrap` creates the admin user from `LUKA_ADMIN_*` and the default project. Then:

- Admin (LLM call log, batches, periodic tasks): http://localhost:8000/admin/
- The app: http://localhost:5173
- API docs (Swagger): http://localhost:8000/api/docs/. Log in first via http://localhost:8000/admin/.
  These pages are unauthenticated, so prod doesn't serve them; set `DJANGO_API_DOCS=true` to enable them on a staging service.
- Real API smoke test: `docker compose exec web python manage.py llm_smoke`

<details>
<summary>Upgrading a database created before the Helmly → Luka rename</summary>

The Postgres role and database were renamed from `helmly` to `luka` (and from `sift` to `helmly` before that). `POSTGRES_*` only applies when the volume is first initialised, so an existing volume still has the old role and `migrate` fails with `password authentication failed for user "luka"`.

Either start fresh (`docker compose down -v`, which **deletes local data**), or rename in place and keep it:

```bash
docker compose up -d postgres
docker compose exec -T postgres psql -U helmly -d postgres <<'SQL'
ALTER DATABASE helmly RENAME TO luka;
CREATE ROLE luka SUPERUSER LOGIN PASSWORD 'luka';
ALTER DATABASE luka OWNER TO luka;
SQL
docker compose exec -T postgres psql -U luka -d luka <<'SQL'
DO $$
DECLARE r record;
BEGIN
  EXECUTE 'ALTER SCHEMA public OWNER TO luka';
  FOR r IN SELECT tablename FROM pg_tables WHERE schemaname='public' LOOP
    EXECUTE format('ALTER TABLE public.%I OWNER TO luka', r.tablename);
  END LOOP;
  FOR r IN SELECT sequencename FROM pg_sequences WHERE schemaname='public' LOOP
    EXECUTE format('ALTER SEQUENCE public.%I OWNER TO luka', r.sequencename);
  END LOOP;
END $$;
SQL
```

The old `helmly` role (and `sift`, on a volume that predates both renames) stays behind. If it is Postgres's bootstrap superuser, it owns pinned system catalogs and can't be dropped. Nothing uses it.

Also update `.env`: `LUKA_ADMIN_*` (was `HELMLY_ADMIN_*`), `DATABASE_URL=postgres://luka:luka@localhost:5433/luka` and `LANGSMITH_PROJECT=luka`.

On Render, the Blueprint services were renamed too (`helmly-web` → `luka-web`, and so on), so a redeploy creates new services and a new database, and prompts for the secrets again. Move data across with `pg_dump`/`pg_restore` before deleting the old `helmly-*` services.
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
| `LUKA_ADMIN_USERNAME`, `LUKA_ADMIN_PASSWORD`, `LUKA_ADMIN_EMAIL` | The first admin user and their project, created by `bootstrap`. Add more users in Django admin. |
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
| `GIT_HOST` | `github` (default) or `fake`: an in-memory GitHub for local dev, one per process |
| `GITHUB_APP_ID`, `GITHUB_APP_SLUG`, `GITHUB_APP_CLIENT_ID` | The Luka GitHub App (see "GitHub pull requests" below) |
| `GITHUB_APP_PRIVATE_KEY`, `GITHUB_APP_CLIENT_SECRET` | The app's secrets. Never commit them |
| `LUKA_APP_URL` | Where users reach Luka, e.g. `https://luka.example.com`. GitHub sends users back here, and PR descriptions link to drafts from here |

## GitHub pull requests (blog posts)

The Content Agent can open each blog post as a pull request in the project's own repository
(`docs/prds/0002-github-blog-prs.md`). It does this through **one GitHub App per Luka
deployment**. Every customer installs that app on the repositories they choose. Luka stores
only the installation id. It mints tokens that last an hour at most, narrowed to one
repository and the permissions the step needs, and never stores them.

### Register the app (once per deployment)

1. On GitHub, go to **Settings → Developer settings → GitHub Apps → New GitHub App**. To own it
   as an organisation, use the organisation's settings instead.
2. **Name:** for example `Luka` (its URL slug becomes `GITHUB_APP_SLUG`). **Homepage URL:** your
   `LUKA_APP_URL`.
3. **Identifying and authorizing users:**
   - **Callback URL:** `<LUKA_APP_URL>/api/github/callback/`
   - Tick **Request user authorization (OAuth) during installation.** Luka uses this one-time
     authorisation to check that the installation really belongs to the person connecting. Then
     it discards the token.
   - Leave **Expire user authorization tokens** ticked.
4. **Post installation:**
   - **Setup URL:** the same `<LUKA_APP_URL>/api/github/callback/`
   - Tick **Redirect on update**, so changing repository access on GitHub comes back to Luka.
5. **Webhook:** untick **Active**. Luka doesn't receive webhooks.
6. **Repository permissions.** Set these and nothing else:

   | Permission | Access | Why |
   |---|---|---|
   | Contents | Read and write | Create the `luka/…` branch and commit the post's file to it. Check the base branch and that no file with the same name exists there. |
   | Pull requests | Read and write | Open the PR, refresh its description on "Update PR", and find an existing PR on retry. |
   | Metadata | Read-only | Required by GitHub (listing repositories and branches). |

   Leave **Workflows**, **Administration** and every organisation and account permission at
   *No access*. Without Workflows, GitHub itself stops the app from touching
   `.github/workflows/`.
7. **Where can this GitHub App be installed?** Choose *Only on this account* while testing, and
   *Any account* when customers connect their own repositories.
8. Create the app, then on its page:
   - note the **App ID** and **Client ID**
   - **Generate a new client secret**
   - **Generate a private key** (a `.pem` file downloads)
9. Put the values in the server's env file (never in this repo):
   ```
   GIT_HOST=github
   GITHUB_APP_ID=123456
   GITHUB_APP_SLUG=luka
   GITHUB_APP_CLIENT_ID=Iv23li...
   GITHUB_APP_CLIENT_SECRET=...
   GITHUB_APP_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----\n"
   LUKA_APP_URL=https://luka.example.com
   ```
   The private key can be one line with `\n` for line breaks, as above. Restart web and worker.

### What customers do

1. In Luka, **Settings → GitHub pull requests → Connect GitHub.** GitHub's install screen opens.
   Pick **Only select repositories** and choose the blog's repository.
2. Back in Luka, choose the repository, the base branch (where the site deploys from) and the
   folder for posts. Rename frontmatter fields or add constant ones if the site needs them;
   the preview shows the header a post will get. Save.
3. **Protect the base branch on GitHub** (Settings → Branches, or a ruleset that requires a
   pull request with an approval). Luka only ever writes to its own `luka/…` branches and never
   merges, but GitHub can't restrict an app to that, so branch protection is what makes GitHub
   enforce it too. Luka shows a warning while the base branch is unprotected.
4. Optional: on the Content Agent's page, set **Pull requests** to *Automatic*. Every post
   without flags is then opened as a PR when it's written. Flagged posts wait in the inbox.

To revoke access completely, uninstall the app on GitHub. **Disconnect** in Luka only stops
new PRs.

### Rotating the key

GitHub allows two private keys at once. Generate a new one, deploy it, then delete the old one
on the app's page.

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
2. In Render: **New → Blueprint**, then pick the repo and branch. Render prompts once for each secret on `luka-web`:
   - `ANTHROPIC_API_KEY`, `APIFY_TOKEN`, and optionally `LANGSMITH_API_KEY` (set `LANGSMITH_TRACING=true` in the `luka-shared` group to turn tracing on)
   - `LUKA_ADMIN_USERNAME`, `LUKA_ADMIN_PASSWORD`, `LUKA_ADMIN_EMAIL`, for the single admin user
   - `SENTRY_DSN` on the `luka-shared` group, so web, worker and beat all report into one
     project. Leave it blank to deploy with error reporting off.

   `luka-worker` and `luka-beat` read those same secrets from `luka-web`, and `DJANGO_SECRET_KEY` is generated.
3. Every deploy runs `migrate` and `bootstrap` (idempotent) before the new version goes live. The health check is `/api/health/`.
4. Verify:
   - `https://<luka-web host>/api/health/` returns `{"ok": true}`
   - you can log in at `/admin/`
   - in the Render shell for `luka-web`, `python manage.py llm_smoke` makes one cheap real call
5. Onboard with `POST /api/onboarding/start/`, then enable agents with `PATCH /api/agents/<type>/` `{"enabled": true}`. Beat picks up schedule changes without a restart.
6. Once HTTPS is confirmed working, set `DJANGO_HSTS_SECONDS` (for example `31536000`) on `luka-web`. Don't set it before then: browsers cache HSTS.

Notes:
- **Plans:** the Blueprint uses small instance types (`0.5c-512mb` services, `0.1c-256mb` Postgres, `256mb` Key Value). Background workers and `preDeployCommand` need paid plans. See Render's pricing page for current costs.
- **Beat:** run exactly **one** `luka-beat` instance, or scheduled runs fire twice.
- **Redis:** Key Value uses `noeviction`, because it's the Celery broker and queued tasks must never be dropped.
