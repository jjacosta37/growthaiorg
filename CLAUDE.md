# CLAUDE.md — Luka

Working agreement for this repo. The approved plan follows below; keep it up to date as milestones land.

## Conventions
- **Platform, not bespoke.** Luka is built as a product for any company. Never put customer-specific or industry-specific logic, names or examples in code, prompts, tests or docs. Industry rules live in `backend/policies/*.yaml` (policy packs: data). Each project has an editable `ContentPolicy` (rules, author role, disclosure, blog disclaimer) that is rendered into every call's guardrails and used by the compliance lint. Prompts refer to "the content rules" and the context docs. `tests/test_platform_neutral.py` enforces this for active prompts and code. When a live run exposes a problem, fix it generically (a rule, a setting, a better generic prompt) and check that the fix doesn't assume one industry.
- Stack is fixed: Django + DRF + Postgres, Celery + beat + Redis, Vite React TS, `anthropic` SDK. No LangChain/LangGraph/Agent SDK.
- **Only `backend/llm/` imports `anthropic`.** Pipelines call `llm.complete(...)` / `llm.batch.*`.
- **Only `llm/tracing.py` imports `langsmith`**, for the same reason only `backend/llm/` imports `anthropic`: it is where tracing is made unable to break a run (guarded span creation, `LANGSMITH_TRACING` honoured, a failed wrap degrading to an untraced client). Everything else imports `traceable` / `trace_group` / `trace_tool` from `llm.tracing`.
- **Only `apps/agents/external.py` writes `ExternalUsage`.** Non-LLM provider calls go through `record_external(...)`, which writes the row and reports the call together. Both rules are enforced by `tests/test_observability.py`.
- Model IDs come from `settings.LLM_MODELS` (`fast` = `claude-haiku-4-5-20251001`, `writer` = `claude-sonnet-5`). Never hardcode.
- Prompts live in `backend/prompts/<task>/vN.md` (YAML frontmatter + Jinja body). Never inline prompt strings. Bump the version instead of editing a prompt that has produced drafts. Superseded versions are deleted once no pending batch uses them (git keeps the history).
- External data goes through adapters in `backend/providers/`. Pipelines depend on the interface, not Apify.
- Agents are deterministic Celery pipelines. No autonomous loops.
- Tests mock every Anthropic and Apify call. Run with `docker compose run --rm web pytest` (or `pytest` in `backend/`).
- Don't use trafilatura's `deduplicate=True`: its cache lasts the whole process, so in a long-lived worker it drops text seen on earlier pages or in earlier crawls.
- Frontend styling is only `frontend/src/styles/tokens.css` variables. No visual polish until the design system lands. The token names, components and screens are specified in `docs/design-brief.md` (the Claude Design brief); build against those names.

## Deployment and threat model

- **Production is a Mac mini on the operator's private (home) network, not Render.** It runs Docker Compose behind Caddy. The host side lives in the separate `mini-infra` repo: the compose file, the host proxy that routes `/api`, `/admin` and `/static` to Django, and the production env files. This repo provides the images (`backend/Dockerfile`, `frontend/Dockerfile.prod`).
- **`render.yaml` and the Render notes in the README are legacy.** Nothing is deployed from them. Don't extend them, and don't design anything around Render features such as rewrites, `RENDER_*` env vars or managed Postgres.
- **What hosting at home means for code:**
  - The server's network is a home LAN. Anything the worker can be made to fetch can reach the router, other devices and services on the Mac itself.
  - Every outbound request leaves from the operator's residential IP. A request to a host a tenant chooses reveals that IP, and the traffic is attributed to the operator. This is a known issue that scans flag as MEDIUM. Fixing it isn't required for now; it will be fixed later with an egress proxy or relay (`docs/security-patterns.md` §6 and §14 "Accepted risks"). The SSRF rules are not relaxed.
  - `docs/security-patterns.md` §1 and §6 hold the rules.
- **Assume the login page is on the internet and any account may be hostile.** A public login, possibly with signup, is planned, perhaps while Luka is still on the mini. "Accounts are created by an admin" is never a reason to accept a risk or lower a finding's severity.

## Claude Code on the web (sandbox)
`.claude/hooks/session-start.sh` prepares a cloud session: a Python 3.13 venv at `.venv` (on `PATH`), Postgres on `localhost:5433` (role/db `luka`, migrated and bootstrapped with `admin`/`admin`), Redis on 6379, `frontend/node_modules`, and `REDDIT_SOURCE=fake`. No Docker. Checks: `pytest` and `ruff check .` in `backend/`; `npm run lint` and `npm test` in `frontend/`. Run the app with `python manage.py runserver` (`config.settings.dev`) and `npm run dev`. Real LLM or Apify calls need keys in the environment's secrets.

## Git workflow

Work happens both in local sessions and in Claude Code on the web, which clones from GitHub. Neither can see the other's unpushed commits, so `main` only ever changes through merged PRs.

- **Never commit to `main`.** Start from an up-to-date main and branch: `git switch main && git pull`, then `git switch -c <type>/<short-name>` (`feat/`, `fix/`, `chore/`, `docs/`). Commit there, push, open a PR, merge. Local `main` then only fast-forwards and never diverges.
- **Sync at every handoff.** Push before moving work to a web session. Pull `main` (and rebase any open branch with `git rebase origin/main`) before resuming locally. At the start of a local session, `git fetch` and check whether the branch is behind before writing code.
- **Resolve conflicts on the branch, never on `main`.** Rebase the branch onto `origin/main`, fix the conflict there, and force-push the branch with `--force-with-lease`. Never force-push `main`.
- **Keep branches short-lived**, one feature each, merged soon. `CLAUDE.md` and `.claude/settings.json` change in most sessions and are where conflicts land. Keep edits to them small, and when both sides added entries (hooks, rules), keep both.
- Recommended git config, once per machine: `git config --global pull.rebase true` and `git config --global rebase.autoStash true`.

## Feature PRDs

Complex features start with `/prd`: product questions, then a short PRD in `docs/prds/` whose acceptance criteria the user explicitly accepts before any implementation planning (`docs/prds/README.md` has the template and lifecycle).

- **A plan built from a PRD maps every AC** to the steps that deliver it and to how it will be verified, and adds nothing the PRD's Out list excludes.
- **ACs are a contract.** If implementation shows one is wrong or impossible, stop and ask. An approved change is logged under "Changes after agreement", never made silently.
- Set the status to `building` when implementation starts and to `shipped` when the PR merges. The PR description lists every AC with ✅ and how it was checked.

## Feature docs

After a feature merges, `/feature-doc <feature>` records it in `docs/features/`: how it behaves, why it was built that way, and how it works in the code, checked against the code (`docs/features/README.md` has the template). When a later change alters a documented feature, update its doc in the same way rather than adding a new one.

## Logging and error reporting

Production has no debugger attached: the log stream, the `AgentRun` row and the Sentry issue are the only things that will ever explain a failure. Write them as if they are all you get, because they are.

- **One logger per module:** `log = logging.getLogger(__name__)`. Never `print`, never the root logger, never a logger named by hand.
- **Levels carry meaning — they are the routing table, not decoration:**
  - `ERROR` — a flow failed and someone needs to know. Files a Sentry issue automatically, from any logger except the two `init_sentry` ignores by name (`apps.api`, which `DjangoIntegration` already covers, and `apps.agents.runs.events`, which reports through `RunReporter` instead). Don't add to that list without replacing the reporting some other way.
  - `WARNING` — degraded but carried on. Log stream and Sentry breadcrumb only.
  - `INFO` — milestones of a mission-critical flow: what started, what it decided, what it produced, plus the identifiers needed to find the rows.
  - `DEBUG` — not used in shipped code paths.
- **Inside a pipeline, report through `RunReporter`, not the logger.** `reporter.step/success/warning/error` writes the `RunEvent` the UI reads, mirrors it to the log at the matching level, and leaves a Sentry breadcrumb. A bare `log.info` inside a pipeline is invisible to the user.
- **Pass the exception: `reporter.error(msg, exc=exc)`.** Whenever one is in hand, it is what gets reported, and it groups by exception type and stack instead of by interpolated message text. Without `exc` nothing is reported — correct for an aggregate ("3 posts couldn't be scored"), wrong for a caught exception.
- **`reporter.warning` never files an issue**, by design. Use it for degradation the run tolerated; use `error` when a step was abandoned.
- **Never swallow an exception silently.** A caught exception is either reported with `exc=`, or logged with `exc_info=True`. `except Exception: pass` is not acceptable, and neither is logging only `str(exc)` where a traceback was available.
- **Log identifiers, never content.** Project/draft/run/page ids, URLs, counts, durations, costs — yes. Crawled page text, draft bodies, context documents, prompts, API keys — never. Sentry is configured with no PII, no request bodies and no frame locals for this reason (`backend/config/observability.py`); don't reintroduce the leak by hand.
- **Flows that must log:** every agent run's start, each step and its outcome; every external call (LLM, Apify, crawl) with its result; every Celery task that runs outside `running()`; anything that spends money or writes something a user will see.
- **Spend and usage go to the database, not the log.** `LLMCall` and `ExternalUsage` are the record; `apps/stats/` reads them. A log line about cost is for debugging only, never the source of truth.
- **Tests never reach Sentry** (no DSN in `config.settings.test`). Assert on `RunEvent` rows and `run.stats` for domain failures, and use `caplog` for log level. See `backend/tests/test_observability.py`.
- **The frontend reports nothing** (decided, not overlooked). `ErrorBoundary` in `frontend/src/components/feedback.tsx` stops a render throw from blanking the app and writes to the viewer's console; nothing leaves the browser. API failures are still covered, because the 500 is reported server-side. Client-side JS errors — a throw in an event handler, an unhandled rejection — leave no trace. Closing that means `@sentry/react` plus source-map upload, or the stack traces are minified and useless.

## Security

`docs/security-patterns.md` defines what secure means for Luka. It covers the tenant boundary, public views, SSRF, model-output effects and the severity rubric, and it holds the register of known concerns. `tests/test_security_patterns.py` enforces its mechanical rules.

- **Run `/security-scan` before every push and every PR.** Fix every CRITICAL and HIGH finding in the same PR, commit, and let the skill mark HEAD. Then paste its `## Security scan` section into the PR description.
  - A `PreToolUse` hook (`.claude/hooks/security-gate.sh`) blocks `git push` and PR creation until HEAD is marked. Any new commit needs a new scan.
  - Don't work around the gate. If a CRITICAL or HIGH finding can't be fixed within the PR, stop and ask.
- **Every new endpoint gets a case in `tests/test_tenancy.py`.** Scoping through `current_project(request)` is the only thing that separates tenants.
- **Adding a trust boundary means updating the patterns doc in the same PR.** That covers a public view, an outbound fetch, an LLM tool, a new effect of model output, a new call multiplier, or a new third party that receives content. The same goes for fixing an item from the known-concerns register: remove it from the register.

## What a run must make visible

A pipeline inherits three things for free: `running()` gives it a LangSmith span, the status lifecycle, Sentry tags and a `RunReporter`; `llm.complete()` / `llm.batch.*` trace every call and write the `LLMCall` row; and anything sent through the reporter becomes a `RunEvent`, a log line and a breadcrumb. **Nothing below is automatic** — a new agent gets none of it unless its author opts in, and the failure mode is a run that looks fine and explains nothing.

- **Wrap every external call in `trace_tool`, in the adapter rather than the pipeline.** Otherwise the call is an unexplained gap in the trace between two LLM spans — which is exactly what an Apify search was. Fill the yielded dict with the provider's own facts: run id, status, item counts, cost, duration.
- **Report every external call with `record_external`.** It writes the `ExternalUsage` row and the `RunEvent` in one step, so a call can never be costed but invisible. It warns when the provider degraded and informs when it didn't; don't also hand-write a warning for the same failure.
- **A provider result carries what the trail needs to explain it:** `status`, `duration_ms`, `items_raw` (before mapping, dedupe and truncation) and, where the provider fans out, how many requests it took. See `RedditSearchResult`. The pipeline must be able to report these without knowing which provider ran.
- **Detail goes in `RunEvent.data`, not in the message.** The message stays one line; counts, ids, breakdowns and distributions ride in `**data`, which every `reporter.*` method accepts.
- **Report what was considered, not only what was produced.** A step that filters says what it dropped and why: a per-key breakdown that reports an explicit `0` for a configured key that returned nothing (`by_subreddit`), and a distribution plus a capped top-N for a scoring pass (`report_scores` in `apps/reddit/pipeline.py`). "Nothing came back" is a fact, and it has to be a reported one.
- **A step both paths can reach is reported from one shared function**, so a batched run is not second-class in the trail.
- **`data` is JSON, and identifiers only.** `Decimal` is not serialisable — convert at the boundary, as `record_external` does. Ids, counts, scores, durations and costs, yes; crawled text, draft bodies, post bodies, no. Model rationale (a relevance `reason`) is truncated, because the full text is already on the row. This is the "log identifiers, never content" rule above, and `data` is not an exception to it.

# Luka — implementation plan

## Context
Luka is an AI growth assistant for a company's marketing. Users own projects: each project is one company's workspace, and a user can own several and switch between them. Accounts are created by an admin (Django admin or `manage.py bootstrap`); there is no public signup. It crawls the company's website, writes context docs, and runs three scheduled "agents" (Reddit, Content, X). Each agent is a deterministic Celery pipeline that drafts content into a triage inbox. Nothing is published automatically.

**How this differs from the existing code:** the repo has one commit containing a 1-line `README.md`. Nothing was built from the earlier spec, so there's nothing to reconcile. This is a greenfield build.

## Decisions and flags (please check these)
1. **Apify actor: `harshmaur/reddit-scraper`.** Its `withinCommunity` option runs a keyword search inside one subreddit, which is exactly our subreddit × keyword model. It supports sort `new` plus a time range, returns score, comment count and created time, and costs about $2 per 1k results plus $0.02 per run. Its store page reports 99.3% run success. The fallback is `trudax/reddit-scraper-lite` (largest user base, 4.57★, $3.40 per 1k, `searches` + `startUrls`). The actor ID and input mapping live in `providers/reddit/apify.py`, so switching is a config change. Before M3 I'll make one real test run of each actor to confirm the output fields.
2. **Status line and progress: polling, not SSE.** TanStack Query polls `/api/status` every 2s while a run is active and every 15s when idle. SSE under Django needs ASGI and long-lived connections on Render, which isn't worth it at this scale. Progress events go to a `RunEvent` table, so SSE can be added later with no model changes.
3. **Render session auth and the separate static site** (superseded: production moved to the Mac mini, where the host's Caddy routes `/api` to Django so the API stays same-origin; see "Deployment and threat model"). The frontend static site rewrites `/api/*` to the web service, so the browser sees the API on the same origin. That avoids SameSite=None cookies and CORS. I'll check this works in M6. If Render's rewrite doesn't pass cookies through correctly, the fallback is cross-site cookies (`SESSION_COOKIE_SAMESITE=None`, `CSRF_TRUSTED_ORIGINS`, `django-cors-headers` with credentials).
4. **Editable schedules: `django-celery-beat` DatabaseScheduler.** Saving an `AgentConfig` upserts its `PeriodicTask` (crontab), and beat picks up the change without a restart.
5. **Claude API details that shape the `llm/` module:**
   - Prompt caches are **per model**. Context docs cached for Sonnet aren't reused by Haiku. That's fine because each model builds its own warm cache. Haiku 4.5 only caches prefixes of **4096 tokens or more**. The context docs will usually be longer than that; if not, the call simply isn't cached and nothing breaks.
   - Sonnet 5 uses adaptive thinking by default and rejects `temperature` and assistant prefill. Each prompt file sets `effort` in its frontmatter (generation: `medium`; competitor research: `high`). Output format is controlled with structured outputs, not prefill.
   - Structured outputs use `client.messages.parse(output_format=PydanticModel)`. Batches pass `output_config.format` with the JSON schema generated from the same Pydantic model.
   - Web search uses `web_search_20260209` (Sonnet 5 supports it) with `max_uses` set. Server-tool errors arrive as result blocks, not exceptions, so the code checks for them.
   - Every response is checked for `stop_reason` of `refusal` or `max_tokens` before parsing. Either one is logged as a failed call.
   - LangSmith: `wrap_anthropic(client)` traces sync calls. The wrapper can't see batch submit and collect, so those are wrapped in `@traceable` spans that record each result's usage.
6. **JavaScript-rendered pages (decided during M2):** our crawler reads server HTML and decodes Next.js's embedded content. Pages that are still thin go to `ApifyRenderer` (Apify Website Content Crawler with a real browser), behind the `PageRenderer` interface in `providers/crawl/render.py`. Apify spend is logged in `ExternalUsage`. Many modern marketing sites (client-rendered SPAs) need this.
7. **Content policy (decided after M4):** replaces hardcoded, industry-specific guardrails. Policy packs (`general`, `financial_services`, `health_wellness`) are YAML files, and packs extend `general`. Onboarding's first model step identifies the product name and suggests a pack; a user-chosen or edited policy is never overwritten. The Compliance Guidelines doc is rendered from the pack and policy, and stays in sync unless hand-edited.
8. **Compliance lint (one small addition; I'll drop it if you don't want it):** after generation, a cheap Haiku call checks the draft against the hard rules. It returns `{flags: [{rule, excerpt}]}`, shown as a warning in the detail pane. It never blocks a draft.

## Project structure
```
backend/
  config/            settings/{base,dev,prod}.py, celery.py, urls.py
  apps/core/         Project, session login/logout/me, /api/status
  apps/context/      CrawledPage, ContextDocument(+Revision); crawler; onboarding pipeline
  apps/agents/       AgentConfig, AgentRun, RunEvent; registry; beat sync; run-now
  apps/inbox/        Draft, DraftVersion; list/detail/actions API
  apps/reddit/       RedditPost; pipeline (fetch→dedupe→score→draft)
  apps/content/      BlogTopic; pipeline (propose→draft)
  apps/xagent/       pipeline (plan formats→draft)
  apps/stats/        aggregation endpoints
  llm/               Django app: client.py, prompts.py, context.py, batch.py, pricing.py,
                     schemas.py, models.py (LLMCall, LLMBatch), tracing.py
  providers/         reddit/{base.py, apify.py, fake.py}; crawl/{sitemap.py, fetch.py, extract.py}
  prompts/           <task>/v1.md … (YAML frontmatter + Jinja body); templates/compliance.md
  tests/
frontend/            Vite + React + TS; React Router; TanStack Query; openapi-typescript types
  src/styles/tokens.css (CSS vars, light/dark), src/features/{inbox,agents,context,stats,settings}
docker-compose.yml   web, worker, beat, postgres, redis, frontend
render.yaml, .env.example, README.md, CLAUDE.md
```

## `llm/` module (the only place the Anthropic SDK is used)
- `complete(task, variables, project, *, run=None) -> LLMResult(parsed, text, call_id)`. `task` points to a prompt file. The frontmatter sets `model_tier` (`fast` or `writer`, mapped to `settings.LLM_MODELS`), `max_tokens`, `effort`, `schema` (a Pydantic class in `llm/schemas.py`) and `tools` (e.g. `web_search`).
- **Cache layout:** the system prompt is `[guardrails + context docs block (cache_control)] + [task instructions]`. The context block is rendered deterministically (fixed document order, no timestamps), so every task on a given model shares the same cached prefix. Pages crawled during onboarding use the same pattern.
- **Retries:** the SDK's `max_retries` handles transport errors. One extra retry runs if the structured output fails validation.
- **`batch.submit(task, items) -> LLMBatch`** and **`batch.collect(llm_batch)`**. Results are keyed by `custom_id`. Each result writes an `LLMCall` with `is_batch=True` and costs at 50%.
- `LLMCall` stores task, model, prompt name/version/hash, input, output, cache-read and cache-write tokens, cost_usd, latency, status, error, langsmith_run_id, and FK `agent_run`. Prices come from `settings.LLM_PRICING`.
- Every prompt file carries a version string and a content hash. Every `DraftVersion` stores the prompt version and model that produced it.

## Data model
- **Project**: owner (FK User), name, website_url, product_summary, competitors (JSON list of {name, url}), onboarded_at. Every domain row hangs off a project; the project a request acts on is resolved per request in `apps/core/selection.py` (X-Project-Id header, else the session, else the user's first). There is deliberately no global `Project.current()`.
- **CrawledPage**: project, url (unique per project), title, content_text, content_hash, fetched_at.
- **ContextDocument**: project, kind (product, audience, brand_voice, competitors, content_strategy, compliance), content_md, source (ai/human), prompt_version, model, updated_at.
  **ContextDocumentRevision**: doc, content_md, source, created_at. Kept for history and rollback.
- **AgentConfig**: project, agent_type (reddit/content/x), enabled, cron, config JSON (validated by a per-agent Pydantic model: Reddit takes subreddits, keywords, threshold, max_posts_per_run, lookback; Content takes cadence and topics_per_run; X takes posts_per_run and format mix), publish_mode (`manual` only for now; the hook for auto-publishing later).
- **AgentRun**: project, kind (onboarding/reddit/content/x/regenerate), trigger (scheduled/manual), status (queued/running/waiting_batch/succeeded/failed), current_step, stats JSON, error, started/finished.
  **RunEvent**: run, ts, level, message. Feeds the progress UI and the status line.
- **RedditPost**: project, reddit_id (unique per project, used for dedupe), subreddit, title, body, url, author, upvotes, num_comments, posted_at, first_seen_run, relevance_score, relevance_reason, reply_worthwhile, scored_at, score_call (FK LLMCall). "Skipped" means scored with no draft.
- **BlogTopic**: project, title, angle, target_keywords, status (proposed/drafted/rejected), requested_by_user.
- **Draft**: project, agent_type, kind (reddit_comment/x_post/x_thread/blog_post), status (new/posted/dismissed), source_reddit_post (FK), blog_topic (FK), current_version (FK), read_at, posted_at, posted_url, dismiss_reason (not_relevant/already_answered/too_promotional/other), dismiss_note, compliance_flags JSON, created_at.
- **DraftVersion**: draft, n, source (ai_initial/ai_regenerated/human_edit), content JSON (validated per kind), nudge, prompt_name/version, model, llm_call FK, created_at. The eval dataset is the last AI version compared with the human-edited or posted version, plus the dismiss reasons.
- **AgentFeedback** (`apps/feedback/`): project, agent_type, draft/draft_version FKs, source (the feedback box, or a regenerate instruction with "remember" ticked), rating (up/down), text, digested_at. Dismissals are deliberately not used as feedback.
  **AgentLearnings**: one per project and agent: `writing_md` + `selection_md`, source (ai/human). A `digest_feedback` run folds new feedback into it (`prompts/feedback/digest`). The Reddit comment prompt gets the writing learnings plus the undigested entries raw; scoring gets the selection learnings. The Reddit config also carries `guidance` (the user's custom instructions).
- **LLMCall**, **LLMBatch** (anthropic_batch_id, status, agent_run, request_count, submitted_at/ended_at), **ApifyRun** (actor_id, apify_run_id, items, cost_usd from `usageTotalUsd`, agent_run).

## Pipelines
- **Onboarding:** fetch the sitemap (and nested indexes) and pick up to `CRAWL_MAX_PAGES` URLs (default 40) on the same host. If there's no sitemap, fall back to a BFS crawl from the homepage. Fetch with httpx, respecting robots.txt, and extract text with trafilatura. Then generate the docs in sequence: product → audience → brand voice → competitors (with web search) → content strategy. Copy the compliance doc from the template. Suggest subreddits and keywords (structured output) and save them to the Reddit config. Each step writes a RunEvent. Fewer than 3 pages found produces a warning state in the UI.
- **Reddit:** for each (subreddit, keyword) pair, fetch through `RedditSource.search()` (the adapter). Dedupe on `reddit_id` against the database. **Scheduled runs:** submit a Haiku scoring batch, set the run to `waiting_batch`, and have a `poll_batch` task re-check every 2 minutes with countdown and a max age. **Manual runs:** score synchronously. After scoring, posts at or above the threshold with `reply_worthwhile` set get a Sonnet comment draft. The prompt includes the subreddit tone and the founder disclosure rule.
- **Content:** propose N topics, passing existing BlogTopic titles and slugs to avoid repeats. Draft a post for the top topic or for a topic I requested. The output is structured: `{title, meta_description, slug, keywords, body_md}`.
- **X:** choose a format and angle mix from config. Pass in the last 30 X drafts to avoid repetition. Output is `{posts: [str]}`. The character limit is checked in code, and anything over 280 characters triggers one regeneration.
- **Regenerate:** a Celery task (with a sync option) that takes the nudge and the previous version and writes a new DraftVersion.

## API (DRF, session auth, CSRF)
`/api/auth/{login,logout,me}`, `/api/status`, `/api/project`, `/api/context/docs[/:kind][/regenerate]`, `/api/context/recrawl`, `/api/onboarding/start`, `/api/runs[/:id/events]`, `/api/agents/:type/{config,run-now,runs,skipped}`, `/api/drafts?agent=&status=&sort=` plus `/:id/{edit,regenerate,mark-posted,dismiss,read}`, `/api/stats`. Schema generated with drf-spectacular, and TS types generated from it with openapi-typescript.

## Frontend
Three-pane layout: sidebar (project switcher, Inbox with unread count, per-agent ready counts, Context, Stats, Settings, status line), list (agent and status filters, sort), and a detail pane that switches renderer by `kind`:
- Reddit: thread context plus an editable comment
- X: post cards with a live counter and stacked thread posts
- Content: article preview plus a side panel for SEO fields and "Copy as markdown"

"Copy & open" writes to the clipboard, calls `window.open`, and records a pending item ID. On `visibilitychange` back to the tab, it shows "Did you post it?". Shortcuts: j/k/c/e/r/d, shown as hints. Markdown editing uses a textarea with a react-markdown preview. Competitors and subreddits use chip inputs. Styling is only `tokens.css` (color, type, spacing, radius, light/dark), with no visual polish yet.

## Milestones (each ends runnable)
**Progress:** Phase 1 complete (M1–M6 and the content policy). Phase 2 built (M7–M8); the product was renamed Sift → Helmly alongside it, and later Helmly → Luka (with the rocket mark).

**Phase 1: backend only.** Each milestone is exercised through the DRF API, the browsable API or admin, and pytest. docker-compose leaves out the frontend service until Phase 2.
1. **Skeleton:** Django, DRF, Celery, beat, Postgres, Redis in docker-compose; session auth endpoints; `llm/` with prompt loader, `complete()`, cost logging, LangSmith; `.env.example`; README. Tests: prompt loader, cost calculation, structured parse and retry, refusal handling (SDK mocked).
2. **Onboarding + context API:** crawler, doc generation with web search, RunEvent progress, regenerate and re-crawl endpoints. Tests: sitemap parsing, page limit and host filter, extraction, pipeline with mocked LLM.
3. **Inbox API + Reddit Agent:** Apify adapter plus a fake adapter, dedupe, batch and sync scoring, drafting, draft actions (edit, regenerate, mark posted, dismiss), agent config, run-now, runs and skipped endpoints. Tests: dedupe, adapter mapping, batch submit, poll and collect (including errored and expired results), threshold logic.
4. **Content Agent:** topics and SEO drafts. Tests: topic dedupe, schema parsing.
5. **X Agent:** formats and character limits. Tests: character-limit enforcement and regeneration, recent-draft exclusion.
6. **Stats + deploy:** weekly aggregates, LLM and Apify spend, `render.yaml` (web, worker, beat, Postgres, Redis), deploy docs.

**Phase 2: frontend.** The Vite app against the finished API.
7. Shell, auth, tokens.css, sidebar with status line, inbox list and detail renderers, actions, shortcuts, the "Did you post it?" flow.
8. Context, agent, stats and settings pages; empty and error states; add the static site and `/api` rewrite to `render.yaml`.

## Verification
- `docker compose up` brings up everything. Log in with the superuser from `createsuperuser`.
- `pytest` runs with Anthropic and Apify mocked (`respx` / `unittest.mock`) and `FakeRedditSource`.
- Per milestone: M2, onboard a real company URL and watch progress reach Context. M3, "Run now" on Reddit with real Apify and small limits, then check drafts, skipped list, LLMCall costs, and that LangSmith traces appear. Run one scheduled batch to confirm the `waiting_batch` → drafts flow and that `cache_read_input_tokens > 0` on repeat calls. M6, deploy to the production host (originally the Render Blueprint, now the Mac mini via `mini-infra`) and confirm login works through the proxy.
