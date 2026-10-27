---
id: 0004
title: Suggest more subreddits and keywords
status: building
created: 2026-10-27
agreed: 2026-10-27
branch: claude/stoic-bell-1i47nl
---
# Suggest more subreddits and keywords

## Problem
After a few weeks, most posts a Reddit run finds are "seen before": the same subreddits and keywords keep returning the posts the agent already has. Subreddits and keywords are suggested only once, at onboarding, and only when the config is empty, so the user has no help widening the search once it goes stale. Finding new communities and search terms by hand is exactly the research the agent should save them.

## Outcome
- From the Reddit Agent page, the user can ask for more subreddits and keywords at any time and add the ones they like in a couple of clicks.
- Suggestions learn from what the agent has already found: they lean towards what produces relevant posts and away from what produces nothing.
- The user can see when the "seen before" problem is caused by their time window and schedule rather than by their targets.

## Scope
**In:**
- A "Suggest more" action on the Reddit Agent page that proposes new subreddits and new keywords, each with a reason.
- Suggestions informed by the context docs, the current config and the project's recent Reddit run history.
- Picking which suggestions to add; dismissing ones that don't fit so they aren't suggested again.
- A hint when the time window is much longer than the gap between scheduled runs.

**Out (non-goals):**
- Web search while suggesting (judged to add noise for little gain over the model's knowledge plus run history; possible follow-up).
- Searching Reddit itself to verify or discover subreddits (adds provider spend on every click; possible follow-up).
- Suggesting removals of underperforming subreddits or keywords (reasons may mention them, but nothing proposes or performs a removal).
- Automatic suggestions or automatic changes to the config; suggesting is always started by the user.
- Changing the onboarding suggestion step.
- Changing the time window, schedule or max-posts settings automatically.

## Behaviour
1. On the Reddit Agent page the user clicks **Suggest more**. While it works, the action shows progress and can't be started twice; the rest of the page stays usable.
2. A list appears: suggested subreddits and suggested keywords, each with a one-line reason. None of them is already in the config or was dismissed before.
3. The user ticks the ones they want and clicks **Add**. They're appended to the config; nothing else in the config changes. The next run (scheduled or Run now) uses them.
4. The user can dismiss a suggestion; it won't be suggested again for this project.
5. If nothing new can be suggested, the user is told so. If suggesting fails, the user sees an error, can retry, and the config is untouched.
6. Separately, when the time window is much longer than the gap between scheduled runs, the page shows a one-line hint that repeats are expected for that reason.

## Acceptance criteria
- **AC-1** The Reddit Agent page has a "Suggest more" action. Using it shows suggested subreddits and suggested keywords, each with a one-line reason. *(verify: both)*
- **AC-2** While suggesting is in progress the action shows progress and can't be started again; the rest of the page stays usable. *(verify: manual)*
- **AC-3** No suggestion duplicates a subreddit or keyword already in the config (ignoring case, a leading "r/" and extra spaces) or one the user dismissed for this project. *(verify: test)*
- **AC-4** Suggestions are informed by the project's context docs, its current subreddits and keywords, and its Reddit run history over the last 30 days: for each current subreddit, how many posts it returned, how many were new and how many were drafted; for each current keyword, how many recent posts mention it. A test confirms this summary reaches the model, including subreddits that returned nothing. *(verify: test)*
- **AC-5** Nothing is added to the config until the user selects suggestions and clicks Add. Add appends exactly the selected items and changes nothing else in the config; the next run searches them. *(verify: both)*
- **AC-6** A dismissed suggestion is not suggested again for that project. Suggestions the user simply doesn't select are not treated as dismissed. *(verify: test)*
- **AC-7** If adding the selected items would exceed the config's limit on subreddits or keywords, the items over the limit can't be added and the page says why. *(verify: both)*
- **AC-8** Suggested subreddit names and keywords that the config wouldn't accept if typed by the user (invalid name, too long) are never shown. *(verify: test)*
- **AC-9** When no new suggestion remains after filtering, the user sees a "no new suggestions" message instead of an empty list. *(verify: both)*
- **AC-10** If suggesting fails, the user sees an error and can retry; the config is unchanged. *(verify: test)*
- **AC-11** The latest suggestions stay on the page after a reload or navigating away, until they're added, dismissed, or replaced by a new "Suggest more". *(verify: manual)*
- **AC-12** Each "Suggest more" makes exactly one model call, with no web search and no Reddit or other provider call, and its cost appears in Stats like other model calls. *(verify: test)*
- **AC-13** Suggestions, dismissals and the run history used are scoped to the current project; a user can't see, apply or influence another project's suggestions. *(verify: test)*
- **AC-14** When the Reddit Agent is scheduled and its time window is more than twice the shortest gap between its scheduled runs, the page shows a one-line hint that most results will be repeats for that reason. No hint when the agent has no schedule or the window is within that bound. *(verify: both)*
- **AC-15** Existing projects see no change until they use "Suggest more": their config, onboarding and runs behave as before. *(verify: test)*

## Decisions
- Suggestions are on demand only (a button), never pushed or applied automatically: the user stays in control of what the agent searches.
- No web search and no Reddit lookup: established communities are well covered by the model's knowledge, and run history closes the loop by showing which suggestions actually produce posts.
- No new paid services and no provider spend per click; one model call per use.
- Additive only: the feature adds targets, it never removes them.
- Keyword performance is approximate (the keyword appears in the post), because a run searches all keywords together.
- Only an explicit dismiss counts as a rejection; unselected suggestions can come back.
- The latest suggestions persist across reloads until added, dismissed or replaced.

## Open questions
None.

## Changes after agreement
<!-- YYYY-MM-DD · AC-n · what changed · why (approved by the user) -->
