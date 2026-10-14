---
id: 0001
title: Evidence-backed blog topics
status: shipped
created: 2026-10-13
agreed: 2026-10-13
branch: feat/evidence-backed-topics
---
# Evidence-backed blog topics

## Problem
The Content Agent proposes blog topics from the context documents alone, and its target keywords are the model's guesses. Nothing tells the user whether anyone is actually asking the question or searching for the keyword, so the backlog can't be prioritised on evidence. Meanwhile the Reddit Agent already collects and scores real audience posts, and that demand never reaches the Content Agent.

## Outcome
- Each topic in the backlog shows why it's worth writing: the Reddit posts asking that question, and the search volume and difficulty of its primary keyword.
- The agent drafts the topics with the strongest evidence first, after anything the user requested.
- Search data costs are capped and visible, and a failed lookup never stops topics from being proposed.

## Scope
**In:**
- Using the project's relevant Reddit posts as the source of topic questions, grouping similar posts into one topic
- Looking up search volume and difficulty for proposed and user-requested topics
- A per-project search market (country and language)
- Ranking the drafting order by evidence, and sorting the backlog by it

**Out (non-goals):**
- Posting to Reddit or replying to the posts used as evidence
- SERP or competitor-ranking analysis for a keyword
- Tracking how published posts rank
- Backfilling search data or evidence for topics that existed before this ships
- Refreshing search data for a topic after it has been looked up once
- Other sources of questions (support tickets, sales calls, forums other than Reddit)
- Open-ended keyword research that isn't tied to a proposed or requested topic

## Behaviour
1. A Content Agent run that needs new topics first gathers the project's relevant Reddit posts from the last 30 days. Relevant means scored at or above the Reddit relevance threshold, whether or not a reply was drafted, posted or dismissed. Posts already backing a topic are left out.
2. Similar posts are grouped, and topics are proposed from the groups as well as from the context documents. Each Reddit-backed topic records the posts behind it.
3. Each proposed topic gets a few candidate keywords. Their search volume and difficulty are looked up for the project's market, and the strongest one becomes the topic's primary keyword.
4. Topics with neither Reddit evidence nor search volume are dropped. Reddit-backed topics with little or no search volume are kept and marked "Low volume".
5. The agent drafts user-requested topics first, then the highest-opportunity topic. Opportunity weighs search volume, ease of ranking and Reddit demand with the project's weights: a sensible default the user can adjust. The post targets its primary keyword.
6. In the backlog, each topic shows its Reddit evidence (count, links to the posts) and its primary keyword's volume and difficulty. The backlog can be sorted by these.
7. **No Reddit data:** if Reddit has subreddits and keywords configured, the run first fetches and scores fresh Reddit posts to look for questions, without drafting any replies. If Reddit isn't configured, or the fetch finds nothing relevant, topics are proposed as today, with search data.
8. **Search data fails or the per-run limit is reached:** topics are still proposed without metrics, marked as pending, and looked up on a later run.

## Acceptance criteria
- **AC-1** When proposing topics, the agent uses the project's Reddit posts from the last 30 days that scored at or above the Reddit relevance threshold, including posts whose replies were dismissed or never drafted. Posts below the threshold or older than 30 days are not used. *(verify: test)*
- **AC-2** Similar posts are grouped into one topic rather than producing one topic per post, and each Reddit-backed topic lists the posts behind it. *(verify: test)*
- **AC-3** A post that already backs an existing topic, including a rejected one, is not used as evidence for a new topic. *(verify: test)*
- **AC-4** In the backlog, a Reddit-backed topic shows how many posts back it and links to each one on Reddit. *(verify: manual)*
- **AC-5** Every newly proposed topic and every user-requested topic gets search data: its primary keyword with monthly search volume and difficulty, as reported by the provider. *(verify: both)*
- **AC-6** Each project has a search market (country and language), defaulting to United States / English and editable on the Content Agent page. Lookups use the project's market. Changing it affects later lookups only. *(verify: test)*
- **AC-7** A proposed topic with no Reddit evidence and zero search volume is not added to the backlog. The run reports how many topics were dropped for this reason. A topic whose search data is still pending (lookup failed or deferred) is kept. *(verify: test)*
- **AC-8** A Reddit-backed topic whose primary keyword has low search volume (below 50 searches a month, zero included) is kept and shown as "Low volume". *(verify: both)*
- **AC-9** Drafting order: user-requested topics first (oldest first), then the remaining topics by opportunity. Given two topics that differ in one signal only, the one with higher search volume, lower difficulty or more Reddit posts ranks first. Topics whose search data is still pending rank after topics that have it. *(verify: test)*
- **AC-9a** Each project has opportunity weights for its three signals (search volume, ease of ranking, Reddit demand). They start at a balanced default and are adjusted on the Content Agent page in plain terms (how much each signal matters, e.g. Low / Medium / High), with ready-made presets ("Balanced", "Search first", "Community first") and a way back to the default. No raw numbers or formulas are shown. *(verify: both)*
- **AC-9b** Changing the weights immediately reorders the backlog's opportunity order and changes which topic the next run drafts. Already drafted posts aren't affected. A weight set to the lowest level stops that signal from deciding the order. *(verify: test)*
- **AC-10** The backlog can be sorted by search volume, difficulty, Reddit evidence count and date added. *(verify: manual)*
- **AC-11** A single run looks up at most 50 keywords. Topics that didn't fit are marked pending and looked up on a later run, and the run reports how many were deferred. *(verify: test)*
- **AC-12** The cost of every search data lookup is recorded and shown in Stats alongside the other provider spend. *(verify: test)*
- **AC-13** If the search data lookup fails, the run still proposes and drafts topics. Affected topics are marked pending, the run shows a warning, and the next run retries them. *(verify: test)*
- **AC-14** If a run needs new topics and the project has no unused relevant Reddit posts, but Reddit subreddits and keywords are configured, the run first fetches and scores fresh Reddit posts for topic research, whether or not the Reddit Agent is enabled. This fetch drafts no Reddit replies, uses the Reddit Agent's configured limits, and its spend is recorded like any Reddit fetch. *(verify: test)*
- **AC-14a** Reply-worthy posts found during topic research get reply drafts on the next Reddit Agent run (when it is enabled), exactly as if that run had fetched them itself. They're never fetched or scored twice, and no post gets more than one reply draft. Posts that aren't reply-worthy appear in the Reddit Agent's skipped list as usual. *(verify: test)*
- **AC-14b** If Reddit isn't configured, or the fetch finds no relevant posts, topics are still proposed from the context documents with search data, and the run reports why no Reddit evidence was used. If the fetch fails, the run reports a warning and carries on the same way. *(verify: test)*
- **AC-16** A project's topics only ever use that project's Reddit posts, and its search data and evidence are never visible from another project. *(verify: test)*
- **AC-17** A post drafted from a topic with a primary keyword targets that keyword. It appears in the title, the first paragraph and at least one H2, as the post rules already require. *(verify: test)*
- **AC-18** The run's activity trail reports:
  - how many Reddit posts were considered and how many groups they formed
  - how many topics were proposed, how many were dropped and why
  - how many keywords were looked up, and how many were deferred or failed

  *(verify: test)*

## Decisions
- **Search data provider:** an Apify keyword actor, so it uses the Apify account Luka already has and needs no new account or prepaid balance. DataForSEO was considered and rejected for now because it needs a new account with a $50 minimum balance. Before building, confirm that the actor returns volume and difficulty for the market setting.
- **Difficulty:** shown on the provider's scale (0–100), not re-scaled. Scores from different vendors aren't comparable.
- **Topic research doesn't take replies away from the Reddit Agent:** posts it finds still get reply drafts on the next Reddit run.
- **Opportunity weights are user-adjustable** in plain terms with presets, because what matters (search traffic or community demand) differs by business.
- **"Low volume", not "no search demand"**, so a community-driven topic doesn't look like a mistake.
- **Reddit-only demand is enough** to keep a topic, because a question the community asks is worth answering even when nobody searches for it.
- **Evidence over invention:** a topic needs Reddit evidence or search volume to enter the backlog. User-requested topics are exempt.
- **No backfill:** the only current user clears the existing backlog before using this feature, so pre-existing topics need no handling.
- **Search data is looked up once per topic.** Refreshing it is out of scope, to keep spend predictable.

## Open questions
None.

## Changes after agreement
<!-- YYYY-MM-DD · AC-n · what changed · why (approved by the user) -->
