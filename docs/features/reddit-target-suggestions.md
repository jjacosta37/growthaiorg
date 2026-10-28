---
title: Suggest more subreddits and keywords
status: shipped
prd: docs/prds/0004-reddit-target-suggestions.md
prs: [22]
updated: 2026-10-27
---
# Suggest more subreddits and keywords

A **Suggest more** button on the Reddit Agent page proposes new subreddits and search keywords, based on the project's context and on what the agent's recent runs actually found. You add the ones you like and dismiss the rest.

## Summary
After a few weeks, most posts a Reddit run finds are ones it has already seen. Subreddits and keywords used to be suggested only once, at onboarding. Now you can ask for more at any time. One model call looks at the context docs, at each current subreddit and keyword with how it performed over the last 30 days, and at what you turned down before. It proposes up to 10 subreddits and 15 keywords, each with a one-line reason. Nothing changes until you tick suggestions and press **Add**. Separately, the page now says when the time window itself is the cause of the repeats.

## Why
Users saw run results like "40 found · 38 seen before". There were two causes:
1. **Stale targets.** The same subreddits and keywords keep returning the same posts, and once onboarding had seeded the config, nothing helped widen it.
2. **Window and schedule overlap.** A run that searches the last week but runs every 4 hours sees mostly the same week each time. No choice of targets fixes that, so the user needs to be told.

## How it behaves

**Where:** the Reddit Agent page, in a **Suggestions** card between Configuration and Run history.

**Main flow:**
1. Press **Suggest more**. The button spins and the card says "Looking at your context and recent runs…". It can't be pressed again until the run finishes, and the rest of the page stays usable.
2. Suggestions appear in two groups, **Subreddits** and **Keywords**. Each has a checkbox, the value (`r/name` for subreddits) and a one-line reason.
3. Tick the ones you want and press **Add N**. They're appended to the config and the card drops them. Nothing else in the config changes, and the next run (scheduled or Run now) searches them.
4. Press **×** on a suggestion to dismiss it. It's never suggested again for this project. Suggestions you simply leave unticked aren't treated as dismissed and may come back.

**Rules:**
- A suggestion is never something already in the config or something you dismissed. The comparison ignores case, a leading `r/` and extra spaces.
- Suggested values follow the same rules as typed ones: subreddit names in Reddit's format, keywords of at most 80 characters. Anything else from the model is never shown.
- **Limits:** the config holds at most 20 subreddits and 30 keywords. Once your ticks fill the remaining room, the other items in that group can't be ticked, and the card says how many more fit. When a group is already full, the card says so.
- Suggestions stay on the page, across reloads, until you add or dismiss them or press **Suggest more** again. A new successful run replaces the pending ones.
- If the configuration form has unsaved edits, **Add** is disabled with "Save or reset your configuration changes first". Adding refreshes the form, which would otherwise drop those edits.
- If you type a suggested value into the config yourself, it drops out of the card.

**States:**
- **Before the first use:** "Running out of fresh posts?" with a pointer to the button.
- **Nothing new:** when the model had nothing that survived the filtering: "No new suggestions".
- **Failure:** a red banner "The suggestion run failed. Try again in a moment." with **Retry**. The previous suggestions and the config stay as they were.

**Repeat hint:** when the Reddit Agent is enabled and its time window (hour, day or week) is more than twice the shortest gap between its scheduled runs, a banner under the header says so. For example: "Each run searches the last week of posts but runs every 4 hours, so most results will be posts already seen. A shorter time window or a less frequent schedule fixes that." There's no hint when the agent is disabled or the window is within that bound.

**Onboarding is unchanged.** It still seeds an empty config once.

## Decisions
- **No web search, no Reddit lookup.** Large, established communities are well covered by the model's own knowledge. What matters for "seen before" is whether a target produces new, relevant posts, and only Reddit can answer that. Run history answers it for free after one run, so the suggester learns from the results of its own earlier suggestions. Rejected: web search, which adds noise and cost for little gain; searching all of Reddit to see where matching posts come from, which is strong evidence but costs provider spend on every click. Both are listed as possible follow-ups in the PRD.
- **On demand only, and additive.** Suggestions appear only when you ask, and never change the config by themselves or remove anything. Underperformers can be mentioned in a reason but are never proposed for removal. The user stays in control of what the agent searches, and of its spend.
- **Keyword performance is approximate.** A run searches all keywords together, so Luka can't tell which keyword found a post. "The post's title or body contains the keyword" stands in for it.
- **Only an explicit dismiss counts as a rejection.** Leaving something unticked is often "not now", not "never".
- **A short background run, not a request that waits on the model.** It follows the Learnings digest: progress, a one-at-a-time guard, a run trail and cost attribution come with it, and the card polls while it runs.
- **Pending suggestions are replaced only on success**, so a failed call never wipes what you were looking at.
- **The window hint is a hint, not an automatic fix.** Changing the time window or schedule stays the user's call. The bound is "more than 2× the gap" so a day window on a 12-hour schedule (a normal overlap) isn't flagged.

## How it works

### Flow
1. `POST /api/agents/reddit/suggestions/` creates a `suggest_reddit_targets` AgentRun (409 if one is active for the project) and queues `suggest_targets_task`.
2. `run_suggest_targets` reads the config, computes `target_history`, collects the dismissed values, and makes one `llm.complete("reddit.target_suggestions")` call.
3. The output is normalised and filtered (invalid, already in the config, dismissed, repeated, over the per-run cap). The project's pending rows are deleted and the survivors inserted, in one transaction.
4. The card polls `GET …/suggestions/` while `suggesting` is true, then shows the pending rows.
5. `POST …/suggestions/add/` runs `add_suggestions`: it locks the config, appends the chosen values, re-validates with `RedditAgentConfig` (400 over a limit, nothing changed) and marks the rows `added`.

### Data model
`RedditTargetSuggestion` (`apps/reddit/models.py`):
- `project`, `run`
- `kind`: subreddit or keyword
- `value`: as it would be saved in the config; `key`: lowercased, for dedupe
- `reason`: at most 300 characters
- `status`: pending, added or dismissed
- `created_at`, `decided_at`

Pending rows are the card. Dismissed rows are kept forever as the "never again" list. Added rows are a record of what came from suggestions.

`AgentRun.Kind` gains `suggest_reddit_targets`.

`fetch()` in `apps/reddit/pipeline.py` now also saves its per-subreddit result counts in `run.stats["by_subreddit"]` (it already reported them in a RunEvent). It counts case-insensitively, and it's the history's source for "returned".

### API
| Method | Path | Does |
|---|---|---|
| GET | `/api/agents/reddit/suggestions/` | `suggesting`, `last_error`, `nothing_new`, pending `subreddits` / `keywords` (`{id, value, reason}`), `room` and `limits` |
| POST | `/api/agents/reddit/suggestions/` | Start "Suggest more"; 202, or 409 while one runs |
| POST | `/api/agents/reddit/suggestions/add/` | `{ids}` (1–100): append the chosen pending suggestions; 400 with the reason over a limit |
| POST | `/api/agents/reddit/suggestions/<id>/dismiss/` | Dismiss one pending suggestion; 404 otherwise |

`GET /api/agents/<type>/` gains `repeat_hint` (`{time_window, window_hours, gap_hours}` or null, Reddit only), from `repeat_hint` in `apps/agents/api.py`. That function uses `min_gap` from `apps/agents/schedule.py`, which `too_frequent` now uses as well.

### Pipelines and tasks
- `suggest_targets_task` (`apps/reddit/tasks.py`) wraps `run_suggest_targets` in `running()`.
- `target_history` (`apps/reddit/suggestions.py`) covers the last `HISTORY_DAYS` (30) days:
  - Per current subreddit: `returned` (the sum of `by_subreddit` over Reddit and Content runs; topic research searches the same targets), `new` (posts first fetched in the window) and `drafted`.
  - Per current keyword: `mentions` and `drafted`.
  - Targets with zero results are always listed.

### LLM calls
`backend/prompts/reddit/target_suggestions/v1.md`:
- Writer tier, `effort: low`, `max_tokens` 4000, schema `RedditTargetSuggestions`, no tools.
- It includes the cached context block, but not the guardrails: it writes nothing a reader sees.
- **Input:** the current targets with their numbers, and up to `DISMISSED_SHOWN` (200) most recent dismissed values. All of it is the user's own data; no post text goes in.
- **Output:** subreddits `{name, reason}` and keywords `{term, reason}`, capped in code at `MAX_SUGGESTED_SUBREDDITS` (10) and `MAX_SUGGESTED_KEYWORDS` (15).
- **Bound:** one call per click, one active run per project.

### Frontend
- `TargetSuggestions` (`frontend/src/features/agents/TargetSuggestions.tsx`) is mounted in `AgentPage.tsx` for the Reddit agent.
- Hooks in `lib/queries.ts`: `useRedditSuggestions` (polls every 2s while suggesting), `useSuggestTargets`, `useAddSuggestions` and `useDismissSuggestion`.
- `RedditConfigForm` reports unsaved edits through `onDirtyChange`.
- The repeat banner text comes from `repeatHintText` in `lib/format.ts`.

## Security and tenancy
- Every query is filtered by `current_project(request)`. Another project's suggestion ids are ignored by Add and are a 404 for dismiss. Covered by `test_reddit_target_suggestions_are_scoped` in `tests/test_tenancy.py`.
- New model-output effect: the `docs/security-patterns.md` §7 allowlist row "Propose new Reddit subreddits / keywords". The output is stored only as pending rows, filtered to the config's format and length rules, and only a person's Add puts it in the config, re-validated against the count limits.
- Spend: the §11 bullet. One call per click, no tools or provider call, one active run per project, and the targets it adds stay under the existing subreddit and keyword caps that bound Apify spend.

## Observability
- Each use is an AgentRun of kind `suggest_reddit_targets` with:
  - a step event (counts of current targets and dismissals)
  - a success event whose data lists what was suggested and `dropped` (`invalid`, `existing`, `dismissed`, `over_cap`)
  - `stats.suggested`
- Its LLMCall is attached to the run. Stats counts its cost under **reddit** (`RUN_KIND_GROUP` in `apps/stats/service.py`).
- A failed call fails the run through `running()`, which reports it to Sentry. The card shows a fixed message, not the exception text; the run's error and events hold the detail.

## Testing
- `backend/tests/test_reddit_suggestions.py`:
  - suggestions with reasons and one tool-free call
  - the 409 guard
  - filtering of existing, dismissed and invalid values
  - history numbers in the prompt, including a subreddit that found nothing
  - Add appends exactly the selection
  - the limit refusal
  - dismissed values never return
  - nothing new
  - a failure keeps the previous state
  - replacement on a new run
  - a value typed into the config drops out of the card
  - Stats attribution
  - the repeat hint cases
  - an untouched existing config
- `backend/tests/test_tenancy.py`: scoping, as above.
- `backend/tests/test_schedule.py` (`test_min_gap`) and `frontend/src/lib/format.test.ts` (`repeatHintText`).
- **Checked by hand** in the sandbox, against a fake model client: the button's busy state, suggestions surviving a reload, Add updating the config chips, dismiss, and the repeat banner. Not yet checked against the real model.

## Limitations and follow-ups
- Suggested subreddits aren't checked against Reddit. One that doesn't exist or is quiet shows up as "returned 0" in the next history, and later suggestions steer away from it.
- Keyword performance is approximate (see Decisions).
- Runs from before this change have no `by_subreddit` in their stats, so "returned" starts at 0 for them; "new" and "drafted" are unaffected.
- Possible follow-ups from the PRD: web search while suggesting, and searching all of Reddit to find where matching posts come from.

## Where to look
| What | Where |
|---|---|
| Pipeline, history, filtering, Add | `backend/apps/reddit/suggestions.py` (`run_suggest_targets`, `target_history`, `add_suggestions`) |
| Model | `backend/apps/reddit/models.py` (`RedditTargetSuggestion`) |
| Endpoints, repeat hint | `backend/apps/agents/api.py` (`RedditSuggestionsView`, `RedditSuggestionsAddView`, `RedditSuggestionDismissView`, `repeat_hint`) |
| Prompt and schema | `backend/prompts/reddit/target_suggestions/v1.md`, `backend/llm/schemas.py` (`RedditTargetSuggestions`) |
| Card | `frontend/src/features/agents/TargetSuggestions.tsx` |

## History
- 2026-10-27 · #22 · first version.
