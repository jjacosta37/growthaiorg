---
title: Friendly agent schedules
status: shipped
prd: docs/prds/0003-friendly-agent-schedules.md
prs: []
updated: 2026-10-16
---
# Friendly agent schedules

Set when each agent runs from plain choices (how often, which days, what time) in the project's own timezone, with a live preview of the next runs. No cron, and never more often than once an hour.

## Summary
Before this change, an agent's schedule was one of six presets or a raw cron expression, and every time was in UTC without saying so. Now a builder offers five ways to say how often an agent runs, a timezone shared by the whole project, and a preview of the next 3 runs while you edit. The server stores the choices as structured JSON. Each schedule becomes one or more celery-beat crontab entries in the project's timezone, and the server refuses any schedule that could run twice within an hour. Old cron schedules were moved over without changing when they fire.

## Why
- Anything outside the presets needed cron, which most users can't write.
- "Every day at 9am" meant 9am UTC, which can be the middle of the user's night.
- Nothing stopped `* * * * *`, so one schedule could multiply LLM and Apify spend 60 times an hour. This was `docs/security-patterns.md` §14 Medium 4, which a backlog item about Content Agent topic research made worse.

## How it behaves
- **Where:** each agent's page (Reddit, Content, X) has a **Schedule** field. It shows the schedule in plain words with the timezone, e.g. "Weekdays at 9:00am and 5:00pm (Europe/Madrid)", and an **Edit** button.
- **Editing:** a "How often" choice, then controls that depend on it:
  - **Every few hours:** every 1, 2, 3, 4, 6, 8 or 12 hours, at a minute past the hour picked in 5-minute steps. Each run is at the same minute past the hour.
  - **Every day:** one to four times of day.
  - **On chosen days:** any set of weekdays (at least one), at one to four times.
  - **Once a week:** one weekday and one time.
  - **Once a month:** a day from 1 to 28 (so no month is skipped) and one time.
  - Switching "How often" keeps the time you already picked where the new choice has one.
- **Times:** "Add time" adds a slot an hour after the last one and is disabled at four. A duplicate time shows an inline message. Times less than an hour apart, including across midnight (23:30 and 00:00), are refused with "Agent schedules can run at most once an hour; space the times at least an hour apart".
- **Preview:** while editing, a box shows the plain-words summary and the next 3 runs in the chosen timezone, refreshed about 250 ms after each change. If the server refuses the schedule, the box shows why and **Save schedule** is disabled. **Discard** leaves the saved schedule unchanged.
- **Timezone:**
  - The editor has a timezone picker (the IANA list, with UTC first). The timezone belongs to the project, so changing it on one agent moves every agent of the project.
  - Local times stay the same: 9:00am stays 9:00am in the new zone.
  - A project that never chose a timezone runs in UTC. The editor proposes the browser's zone ("Proposed from your browser…"), and nothing is stored until you save.
  - Runs follow daylight saving: a daily 9:00am run stays at 9:00am local across the change.
  - A local time that doesn't exist on a spring-forward day (e.g. 02:30) is skipped that day.
- **Next run:** the agent header's "Next run in …" has a tooltip with the local date and time and the zone.
- **Schedules saved before this change:**
  - They keep firing at exactly the same moments.
  - Those matching a builder shape (all the old presets, for example) now open in the builder.
  - Anything else shows as **Custom schedule** with its next 3 runs. It can't be edited, only replaced with **Replace**.
  - A custom schedule that runs more often than hourly keeps running but shows a warning banner until it's replaced. Saving the agent's other settings, or toggling it, leaves it as it is.
- **New projects** get the agents' defaults: Reddit every 4 hours, Content Mondays at 9:00am, X weekdays at 2:00pm, in the project's timezone (UTC until one is chosen).

## Decisions
- **Raw cron is gone from the UI and the API.** The builder covers the shapes people want, and refusing cron on write is what makes the hourly minimum hold for direct API calls too. Rejected: an "advanced" cron field, which would need its own frequency check and brings the cron problem back.
- **One minimum, hourly, for every agent.** It closes the spend risk without per-agent tuning. Rejected: a per-agent minimum, such as daily for Content (PRD Out of scope).
- **Every N hours only offers divisors of 24.** "Every 5 hours" in cron (`*/5`) resets at midnight and leaves an uneven gap. Rejected: any N.
- **Monthly days 1–28.** Every month has the run. Rejected: 1–31 with a "last day" fallback, which is harder to explain.
- **The timezone belongs to the project, not the user.** The agents work for the company's audience, and everyone on the project sees the same times. Rejected: a per-user timezone.
- **Changing the timezone keeps local times.** People think "9am my time". Rejected: keeping the same moments, which would turn 9am Madrid into 3am New York.
- **Schedules store local time plus the project zone; beat does the DST arithmetic.** django-celery-beat evaluates a `CrontabSchedule` in its own timezone (`TzAwareCrontab`). Rejected: converting to UTC crons on save, which breaks on every DST change.
- **The server owns the rules, the wording and the next runs.** The preview calls the same code beat's entries are built from, so the editor can't disagree with what runs. Rejected: duplicating the rules and the DST maths in the browser.
- **Old crons move over without resyncing beat.** Unset timezone means UTC, which is what they ran in, so the existing `PeriodicTask` rows stay valid until the agent is next saved. Shapes the builder can't express become `custom`, never a lossy conversion.
- **No schedule is a "custom" save.** Replacing a custom schedule opens the builder at "Every day at 9:00am". Rejected: seeding with the agent's registered default, which would need another field in the API for little gain.

## How it works
### Flow
1. The editor builds a schedule object and POSTs it, with the chosen zone, to the preview endpoint after a short debounce.
2. `writable_schedule` validates it: the Pydantic models, plus refusing `custom`. Then `summary` and `next_runs` describe it.
3. **Save** PATCHes the agent with `{schedule, timezone?}`. In one transaction the API saves the config, then either `sync_periodic_task(config)` or, when the timezone changed, saves the project and calls `sync_project_tasks(project)`.
4. `sync_periodic_task` turns the schedule into crontab entries (`to_entries`) and upserts one `PeriodicTask` per entry, each on a `CrontabSchedule` with the project's `effective_timezone`. Entries the schedule no longer needs are deleted.
5. Beat's DatabaseScheduler picks the change up and fires `apps.agents.tasks.run_scheduled_agent` in local time.

### Data model
- `AgentConfig.schedule` (JSON) replaces `AgentConfig.cron`. The shapes, by `kind`:
  - `every_hours {hours, minute}`
  - `daily {times}`
  - `weekdays {days, times}`
  - `weekly {day, time}`
  - `monthly {day, time}`
  - `custom {cron}`
- Times are `"HH:MM"` (24h) and days are 0 = Sunday … 6 = Saturday, as in cron.
- Default: `default_schedule()` (every 6 hours) unless the agent registers `default_schedule` in its `AgentSpec`.
- `Project.timezone`: an IANA name, blank until chosen. `Project.effective_timezone` returns it or `"UTC"`.
- Migrations:
  - `agents/0007_agentconfig_schedule`: adds `schedule`, converts each cron with `from_cron`, then drops `cron`. The reverse keeps the first entry only.
  - `core/0004_project_timezone`.
- **Beat entries:** times with different minutes can't share one crontab, so a schedule may need several. Entry 0 keeps the historical name `agent:<project>:<type>`, and extra entries are `agent:<project>:<type>:<i>`. `delete_periodic_tasks` (project deletion) still removes them all by the `agent:<project>:` prefix.

### API
- `GET /api/agents/` and `GET|PATCH /api/agents/<type>/`.
  - The summary now carries `schedule`, `schedule_summary`, `next_runs` (3 ISO times), `schedule_warning` (`"too_frequent"` or null), `timezone` and `timezone_set`, and still `next_run_at`. `cron` is gone.
  - PATCH takes `schedule` (a builder kind) and `timezone`. Errors come back as `{"schedule": [...]}` or `{"timezone": [...]}`.
- `POST /api/agents/schedule-preview/` `{schedule, timezone?}` returns `{summary, next_runs}`. It writes nothing and validates the way a save does. `timezone` defaults to the project's.

### Frontend
- `features/agents/ScheduleEditor.tsx` (`ScheduleEditor`, `Builder`, `KindFields`, `TimeList`, `DayPicker`). It's mounted in `AgentPage.tsx`'s Schedule field. The builder's rows wrap (`.schedule__row` in `agents.css`), so it fits a narrow column.
- `useSchedulePreview` and the `schedule` / `timezone` fields of `useUpdateAgent` are in `lib/queries.ts`, and the `Schedule` type is in `lib/types.ts`.
- `formatInZone` (`lib/format.ts`) formats run times in the project zone. The old `cronToPhrase`, `scheduleLabel`, `SCHEDULE_PRESETS` and `looksLikeCron` were removed.

### Configuration
- The agent defaults are `AgentSpec.default_schedule` in `apps/reddit/agent.py`, `apps/content/agent.py` and `apps/xagent/agent.py`.
- The limits are constants in `apps/agents/schedule.py`: `MIN_GAP_MINUTES` (60) and `MAX_TIMES` (4). The allowed hour steps are the `EveryHours.hours` literal, and the 1–28 bound is `Monthly.day`.
- `tzdata` is now an explicit backend requirement, because the slim Docker image has no system zoneinfo.

## Security and tenancy
- Every read and write goes through `current_project(request)`. The timezone and schedules of another project can't be read or changed, and the preview uses the caller's own project timezone. These are covered in `tests/test_tenancy.py`.
- This closes the old §14 Medium 4 (no minimum interval). §11 "Schedules" in `docs/security-patterns.md` now states the enforced bound: at most hourly, builder choices only, no raw cron by any route. The backlog item about repeated topic research was removed, because its recommended fix was this minimum.
- The preview endpoint adds no spend: it only computes dates.

## Observability
- Scheduled runs show as before, as `AgentRun` rows with trigger "scheduled". The schedule itself is visible in the Django admin (`AgentConfigAdmin.schedule_summary`), and beat's rows are under Periodic tasks, each with its crontab and timezone.
- `next_run_at` logs a WARNING with the config id if a stored schedule can't be read.

## Testing
- `tests/test_schedule.py` covers:
  - the builder's rules (hour steps, 1–4 distinct times, days, 1–28, the hourly gap including across midnight, custom refused)
  - the run times of each kind
  - the plain-words summaries
  - DST (Europe/Madrid on 2026-10-25, and a skipped spring-forward time)
  - beat entries with the project timezone, and cleanup of extra entries
  - a timezone change resyncing every agent with the same local hours
  - API saves and refusals, and the preview
  - old crons converting to schedules that fire at the same moments
  - the migration function
  - the warning on a too-frequent custom schedule
- `tests/test_agents_api.py` covers the summary fields, the PATCH and the new defaults. `tests/test_tenancy.py` covers the schedule, the timezone and the preview.
- `frontend/src/lib/format.test.ts` covers `formatInZone`.
- **Checked by hand** in Chromium against the dev server:
  - building a schedule, the live preview, a refused pair of times disabling Save, and saving with the browser's zone
  - a legacy `*/15` showing as Custom with the warning, Replace, and the Next run tooltip
  - the builder at a 343px-wide column with four times, without horizontal overflow

## Limitations and follow-ups
- **The app itself isn't usable on a phone yet.** The three-pane shell has a 1024px minimum width (`styles/shell.css`), from before this feature. The schedule editor fits a phone-width column, but the page around it scrolls sideways at phone width. AC-16 was narrowed to the editor for this reason, and the phone layout is a backlog item.
- **An ambiguous local time on a fall-back day** (e.g. 02:30 when clocks go back) is shown once in the preview. Whether beat fires it once or twice is decided by celery's crontab (unverified).
- **Times of day are free-form minutes, but every-few-hours offers 5-minute steps.** A schedule saved with another minute keeps it and shows it as an extra option.

## Where to look
| What | Where |
|---|---|
| Schedule models, rules, summary, next runs, beat sync | `backend/apps/agents/schedule.py` (`parse_schedule`, `writable_schedule`, `to_entries`, `next_runs`, `summary`, `sync_periodic_task`, `from_cron`) |
| API fields, PATCH, preview | `backend/apps/agents/api.py` (`schedule_summary`, `AgentDetailView`, `SchedulePreviewView`) |
| Cron → schedule migration | `backend/apps/agents/migrations/0007_agentconfig_schedule.py` |
| Project timezone | `backend/apps/core/models.py` (`Project.timezone`, `effective_timezone`) |
| Agent defaults | `backend/apps/agents/registry.py` (`AgentSpec.default_schedule`) |
| Editor | `frontend/src/features/agents/ScheduleEditor.tsx` |
| Tests | `backend/tests/test_schedule.py` |

## History
- 2026-10-16 · Built: schedule builder, project timezone, hourly minimum, migration of old crons.
