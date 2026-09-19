# CLAUDE.md — Sift

Working agreement for this repo. The approved plan follows below; keep it up to date as milestones land.

## Conventions
- Stack is fixed: Django + DRF + Postgres, Celery + beat + Redis, Vite React TS, `anthropic` SDK. No LangChain/LangGraph/Agent SDK.
- **Only `backend/llm/` imports `anthropic`.** Pipelines call `llm.complete(...)` / `llm.batch.*`.
- Model IDs come from `settings.LLM_MODELS` (`fast` = `claude-haiku-4-5-20251001`, `writer` = `claude-sonnet-5`). Never hardcode.
- Prompts live in `backend/prompts/<task>/vN.md` (YAML frontmatter + Jinja body). Never inline prompt strings. Bump the version instead of editing a prompt that has produced drafts.
- External data goes through adapters in `backend/providers/`. Pipelines depend on the interface, not Apify.
- Agents are deterministic Celery pipelines. No autonomous loops.
- Tests mock every Anthropic and Apify call. Run with `docker compose run --rm web pytest` (or `pytest` in `backend/`).
- Frontend styling is only `frontend/src/styles/tokens.css` variables. No visual polish until the design system lands.

# Sift — implementation plan

## Context
Sift is an internal, single-user growth assistant for OpenWealth. It crawls the website, writes context docs, and runs three scheduled "agents" (Reddit, Content, X). Each agent is a deterministic Celery pipeline that drafts content into a triage inbox. Nothing is published automatically.

**How this differs from the existing code:** the repo has one commit containing a 1-line `README.md`. Nothing was built from the earlier spec, so there's nothing to reconcile. This is a greenfield build.

## Decisions and flags (please check these)
1. **Apify actor: `harshmaur/reddit-scraper`.** Its `withinCommunity` option runs a keyword search inside one subreddit, which is exactly our subreddit × keyword model. It supports sort `new` plus a time range, returns score, comment count and created time, and costs about $2 per 1k results plus $0.02 per run. Its store page reports 99.3% run success. The fallback is `trudax/reddit-scraper-lite` (largest user base, 4.57★, $3.40 per 1k, `searches` + `startUrls`). The actor ID and input mapping live in `providers/reddit/apify.py`, so switching is a config change. Before M3 I'll make one real test run of each actor to confirm the output fields.
2. **Status line and progress: polling, not SSE.** TanStack Query polls `/api/status` every 2s while a run is active and every 15s when idle. SSE under Django needs ASGI and long-lived connections on Render, which isn't worth it for a single user. Progress events go to a `RunEvent` table, so SSE can be added later with no model changes.
3. **Render session auth and the separate static site.** The frontend static site rewrites `/api/*` to the web service, so the browser sees the API on the same origin. That avoids SameSite=None cookies and CORS. I'll check this works in M6. If Render's rewrite doesn't pass cookies through correctly, the fallback is cross-site cookies (`SESSION_COOKIE_SAMESITE=None`, `CSRF_TRUSTED_ORIGINS`, `django-cors-headers` with credentials).
4. **Editable schedules: `django-celery-beat` DatabaseScheduler.** Saving an `AgentConfig` upserts its `PeriodicTask` (crontab), and beat picks up the change without a restart.
5. **Claude API details that shape the `llm/` module:**
   - Prompt caches are **per model**. Context docs cached for Sonnet aren't reused by Haiku. That's fine because each model builds its own warm cache. Haiku 4.5 only caches prefixes of **4096 tokens or more**. The context docs will usually be longer than that; if not, the call simply isn't cached and nothing breaks.
   - Sonnet 5 uses adaptive thinking by default and rejects `temperature` and assistant prefill. Each prompt file sets `effort` in its frontmatter (generation: `medium`; competitor research: `high`). Output format is controlled with structured outputs, not prefill.
   - Structured outputs use `client.messages.parse(output_format=PydanticModel)`. Batches pass `output_config.format` with the JSON schema generated from the same Pydantic model.
   - Web search uses `web_search_20260209` (Sonnet 5 supports it) with `max_uses` set. Server-tool errors arrive as result blocks, not exceptions, so the code checks for them.
   - Every response is checked for `stop_reason` of `refusal` or `max_tokens` before parsing. Either one is logged as a failed call.
   - LangSmith: `wrap_anthropic(client)` traces sync calls. The wrapper can't see batch submit and collect, so those are wrapped in `@traceable` spans that record each result's usage.
6. **Compliance lint (one small addition; I'll drop it if you don't want it):** after generation, a cheap Haiku call checks the draft against the hard rules. It returns `{flags: [{rule, excerpt}]}`, shown as a warning in the detail pane. It never blocks a draft.

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
- **Project**: name, website_url, product_summary, competitors (JSON list of {name, url}), onboarded_at.
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
- Per milestone: M2, onboard openwealth's real URL and watch progress reach Context. M3, "Run now" on Reddit with real Apify and small limits, then check drafts, skipped list, LLMCall costs, and that LangSmith traces appear. Run one scheduled batch to confirm the `waiting_batch` → drafts flow and that `cache_read_input_tokens > 0` on repeat calls. M6, deploy the Blueprint to Render and confirm login works through the rewrite.
