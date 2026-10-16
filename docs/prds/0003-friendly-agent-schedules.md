---
id: 0003
title: Friendly agent schedules
status: building
created: 2026-10-16
agreed: 2026-10-16
branch: claude/wonderful-ramanujan-4hgokv
---
# Friendly agent schedules

## Problem
An agent's schedule today is one of six fixed presets, or a raw cron expression typed into an "Advanced" field. Anything outside the presets (twice a day, Tuesdays and Thursdays, a different hour) needs cron, which most users can't write. Every time is UTC, but the labels don't say so, so "Every day at 9am" can fire in the middle of the user's night. And nothing stops a schedule from running every minute, which multiplies spend (security register §14 Medium 4).

## Outcome
- Anyone can set the schedule they want from plain choices (how often, which days, what time) without knowing cron.
- Times mean what they say: they are in the project's timezone, and the user sees exactly when the next runs will happen before saving.
- No agent can be scheduled to run more often than once an hour.

## Scope
**In:**
- A schedule builder for every agent (Reddit, Content, X), replacing the presets and the cron field
- A timezone per project, used by every agent schedule in that project
- A live preview: a plain-words summary and the next run times
- A minimum interval of one hour, enforced when a schedule is saved
- Moving existing schedules over without changing when they fire

**Out (non-goals):**
- Entering raw cron in the UI
- One-off runs at a set time, "skip next run", or holiday or blackout dates
- A calendar view of upcoming runs across agents
- Different minimum intervals per agent
- Changes to Run now, the enabled toggle or run history
- A timezone per user (the timezone belongs to the project)

## Behaviour
1. On an agent's page, the Schedule field shows the current schedule in plain words with its timezone, e.g. "Weekdays at 9:00am and 5:00pm (Europe/Madrid)".
2. Editing it, the user picks how often:
   - **Every N hours**: N is 1, 2, 3, 4, 6, 8 or 12
   - **Daily**: one to four times of day
   - **On chosen weekdays**: any set of weekdays, one to four times of day
   - **Weekly**: one weekday, one time
   - **Monthly**: one day of the month, one time
3. While editing, the preview updates live: the plain-words summary and the next 3 run times in the project's timezone. Saving and discarding work as they do today.
4. The project's timezone appears next to the schedule and can be changed there. It applies to all the project's agents. A project that has never set one starts with the browser's timezone when a schedule is first saved, and the user sees that choice before saving.
5. A schedule the builder can't express (written by hand earlier) is shown as "Custom schedule" with its next run times. It is read-only, and "Replace" opens the builder.
6. A schedule saved before this change keeps firing at the same moments. The schedule is shown in the project's timezone (UTC until one is set).
7. A schedule that runs more often than once an hour is refused with a clear message, whether it comes from the builder or from the API. An existing one keeps running, is flagged on the agent page, and must be replaced before the schedule can be saved again.

## Acceptance criteria
- **AC-1** On each agent's page (Reddit, Content, X), the user can set a schedule using only the five "how often" options in Behaviour §2, with no cron text field anywhere in the UI. *(verify: both)*
- **AC-2** "Every N hours" offers only 1, 2, 3, 4, 6, 8 and 12, and runs at the same minute past the hour each time. *(verify: test)*
- **AC-3** Daily and chosen-weekday schedules accept one to four distinct times of day. A fifth time or a duplicate can't be added. Chosen weekdays need at least one day. *(verify: both)*
- **AC-4** Monthly accepts days 1–28 only, so every month has a run. *(verify: test)*
- **AC-5** Before saving, the editor shows a plain-words summary that names the timezone, and the next 3 run times in the project's timezone. Both update on every change. *(verify: both)*
- **AC-6** After saving, the run fires at the shown local times, following daylight saving: a daily 9:00am run stays at 9:00am local across a DST change. *(verify: test)*
- **AC-7** Each project has one timezone, chosen from the standard IANA list. It can be changed from any agent's schedule area and applies to all the project's agent schedules. Changing it keeps the local times ("9:00am" stays 9:00am in the new zone) and the preview reflects that before saving. *(verify: both)*
- **AC-8** A project without a timezone proposes the browser's timezone the first time a schedule is edited. It is visible and changeable before saving and is stored only on save. *(verify: manual)*
- **AC-9** Existing schedules fire at exactly the same moments after the upgrade as before it, and are shown in UTC until the project sets a timezone. *(verify: test)*
- **AC-10** A schedule the builder can't represent is shown as "Custom schedule" with its next 3 run times, keeps running unchanged, and can only be replaced, not edited. *(verify: both)*
- **AC-11** Saving a schedule that can run more than once within any 60 minutes is refused with a message saying the minimum is once an hour. This applies to the UI and to direct API calls. *(verify: test)*
- **AC-12** An existing schedule that runs more often than hourly keeps running, shows a warning on its agent page, and can't be saved again until it is replaced with one that meets the minimum. *(verify: both)*
- **AC-13** New projects get today's defaults in the project's timezone: Reddit every 4 hours, Content Mondays at 9:00am, X weekdays at 2:00pm. *(verify: test)*
- **AC-14** One project's timezone or schedule changes don't affect another project's agents, and a user can't read or change another project's schedule or timezone. *(verify: test)*
- **AC-15** Wherever an agent's next run is shown today ("Next run in …"), it is still correct after the change, and hovering or expanding it shows the local date and time. *(verify: manual)*
- **AC-16** The schedule editor works at phone width with no horizontal scroll. *(verify: manual)*
- **AC-17** The security register item for the missing minimum cron interval (§14 Medium 4) and the backlog item it relates to are updated or removed, as far as this change fixes them. *(verify: manual)*

## Decisions
- Raw cron is removed from the UI: the builder covers the useful shapes, and hand-written schedules stay readable through "Custom schedule". (Agreed with the user.)
- The timezone belongs to the project, not the user: the agents serve the company's audience, and every collaborator sees the same times.
- One minimum interval (hourly) for every agent. It is simple, closes the spend risk, and doesn't need per-agent tuning.
- Existing schedules never change when they fire because of this feature.
- No new paid services.

## Open questions
None.

## Changes after agreement
<!-- YYYY-MM-DD · AC-n · what changed · why (approved by the user) -->
