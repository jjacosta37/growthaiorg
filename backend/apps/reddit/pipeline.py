"""Reddit Agent: search → dedupe → score relevance → draft replies for the best posts."""

from collections import Counter
from datetime import timedelta
from urllib.parse import urlsplit

from django.conf import settings
from django.utils import timezone

import llm
from apps.agents.draft_models import draft_model_for
from apps.agents.external import record_external
from apps.agents.models import AgentConfig, AgentRun, AgentType
from apps.agents.runs import RunReporter
from apps.core.models import Project
from apps.feedback.services import learning_variables, selection_learnings
from apps.inbox import compliance, services
from apps.inbox.models import Draft, DraftKind, DraftVersion
from apps.inbox.nudges import nudge_instruction
from apps.policy.service import policy_for
from llm import batch as llm_batch
from llm.models import LLMBatch
from llm.schemas import RedditComment
from providers.reddit import ApifyRedditSource, FakeRedditSource, RedditPostData, RedditSearch, RedditSource

from .config import RedditAgentConfig
from .models import RedditPost

BODY_CHAR_LIMIT = 6000  # long posts are truncated for scoring/drafting (noted in the prompt input)
ZERO_YIELD_RUNS = 3  # searches in a row with no posts at all before it is reported as a failure
KEYWORD_HISTORY_RUNS = 5  # searches a keyword may match nothing in before it is flagged


class SearchYieldError(Exception):
    """A search that keeps succeeding but finds nothing, so the provider or the queries are broken.

    Never raised: it is passed to `reporter.error(exc=...)` so the Sentry issue groups by this type
    rather than by the message, which names counts that change from run to run.
    """


def get_source() -> RedditSource:
    """The configured Reddit source: Apify in production, a fake for local dev."""
    if settings.REDDIT_SOURCE == "fake":
        return FakeRedditSource()
    if not settings.APIFY_TOKEN:
        raise RuntimeError("APIFY_TOKEN is not set (or set REDDIT_SOURCE=fake for local testing)")
    return ApifyRedditSource(settings.APIFY_TOKEN, settings.APIFY_REDDIT_ACTOR,
                             max_charge_usd=settings.APIFY_REDDIT_MAX_CHARGE_USD,
                             max_items=settings.APIFY_REDDIT_MAX_ITEMS)


def load_config(project) -> RedditAgentConfig:
    return RedditAgentConfig.model_validate(AgentConfig.for_project(project, AgentType.REDDIT).config)


# --- Fetch + dedupe ---------------------------------------------------------------------


def safe_post_url(post: RedditPostData) -> str:
    """The post's URL if it is http(s), else its Reddit permalink.

    The URL comes from the provider and is rendered as a link, so a `javascript:` or `data:` URL
    must never be stored (docs/security-patterns.md §8).
    """
    if urlsplit(post.url).scheme in ("http", "https"):
        return post.url
    return f"https://www.reddit.com/r/{post.subreddit}/comments/{post.reddit_id}/"


def store_new_posts(project: Project, run: AgentRun, posts: list[RedditPostData],
                    found_by: str = RedditPost.FoundBy.REDDIT) -> tuple[list[RedditPost], int]:
    """Insert posts we haven't seen before. Returns (new posts, duplicates skipped).

    Args:
        found_by: Which flow fetched them; topic research posts are later handed to a Reddit run.
    """
    ids = [p.reddit_id for p in posts]
    known = set(RedditPost.objects.filter(project=project, reddit_id__in=ids).values_list("reddit_id", flat=True))
    new, seen = [], set()
    for p in posts:
        if p.reddit_id in known or p.reddit_id in seen:
            continue
        seen.add(p.reddit_id)
        new.append(RedditPost(
            project=project, reddit_id=p.reddit_id, subreddit=p.subreddit, title=p.title, body=p.body,
            url=safe_post_url(p), author=p.author, upvotes=p.upvotes, num_comments=p.num_comments, flair=p.flair,
            posted_at=p.posted_at, first_seen_run=run, found_by=found_by,
        ))
    # ignore_conflicts guards against a concurrent run inserting the same post
    RedditPost.objects.bulk_create(new, ignore_conflicts=True)
    new_ids = [p.reddit_id for p in new]
    stored = list(RedditPost.objects.filter(project=project, first_seen_run=run, reddit_id__in=new_ids))
    return stored, len(posts) - len(stored)


def fetch(run: AgentRun, reporter: RunReporter, cfg: RedditAgentConfig, *,
          found_by: str = RedditPost.FoundBy.REDDIT) -> list[RedditPost]:
    """Search the configured subreddits and store the posts not seen before.

    Both the Reddit Agent and the Content Agent's topic research fetch through here, so the two
    report and cost a search the same way; `found_by` tells them apart in the trail and in Stats.

    Raises:
        RuntimeError: The search failed and returned no posts at all.
    """
    research = found_by == RedditPost.FoundBy.TOPIC_RESEARCH
    subs = cfg.subreddits
    preview = ", ".join(f"r/{s}" for s in subs[:2]) + (f" +{len(subs) - 2} more" if len(subs) > 2 else "")
    who = "Researching topics on Reddit:" if research else "Reddit Agent scanning"
    reporter.step(f"{who} {preview}", subreddits=subs, keywords=cfg.keywords,
                  time_window=cfg.time_window, max_posts=cfg.max_posts_per_run)
    source = get_source()
    result = source.search(RedditSearch(subreddits=subs, keywords=cfg.keywords, time_window=cfg.time_window,
                                        max_posts=cfg.max_posts_per_run, include_nsfw=cfg.include_nsfw))
    if result.provider == "apify":
        seconds = round(result.duration_ms / 1000, 1)
        record_external(
            run, reporter, provider="apify", purpose="reddit_topic_research" if research else "reddit_search",
            resource_id=result.resource_id,
            external_run_id=result.external_run_id, status=result.status, items=len(result.posts),
            cost_usd=result.cost_usd, duration_ms=result.duration_ms, error=result.error,
            message=f"Searched {result.queries} quer{'y' if result.queries == 1 else 'ies'} in {seconds}s: "
                    f"{result.items_raw} results, {len(result.posts)} usable (${result.cost_usd})",
            queries=result.queries, items_raw=result.items_raw,
        )
    if result.error and not result.posts:
        raise RuntimeError(f"Reddit search failed: {result.error}")
    if result.error and result.provider != "apify":
        reporter.warning(f"Reddit search had a problem (continuing with {len(result.posts)} posts): {result.error}")
    new, dupes = store_new_posts(run.project, run, result.posts, found_by)
    # Counted here rather than in the adapter: which subreddits produced nothing is the fact
    # this step used to hide, and it must not depend on which provider ran the search.
    # Kept on the run too, as the history "Suggest more" learns from (apps/reddit/suggestions.py).
    counts = Counter(p.subreddit.lower() for p in result.posts)
    by_subreddit = {s: counts.get(s.strip().removeprefix("r/").lower(), 0) for s in subs}
    by_keyword = keyword_hits(result.candidates or result.posts, cfg.keywords)
    history = previous_searches(run)
    run.stats.update(fetched=len(result.posts), new_posts=len(new), duplicates=dupes, by_subreddit=by_subreddit,
                     by_keyword=by_keyword)
    run.save(update_fields=["stats"])
    reporter.event(f"Found {len(result.posts)} posts, {len(new)} new",
                   fetched=len(result.posts), new_posts=len(new), duplicates=dupes,
                   queries=result.queries, by_subreddit=by_subreddit, by_keyword=by_keyword)
    check_search_yield(reporter, len(result.posts), by_keyword, history)
    return new


def keyword_matches(keyword: str, text: str) -> bool:
    """Whether `text` (lowercased) contains the keyword as Reddit search would roughly match it.

    A quoted keyword is an exact phrase; otherwise every word must appear, in any order. Words
    match as substrings, so "contribution" counts a post about "contributions". It is an
    approximation of Reddit's matching, which is why a keyword is only flagged after several
    searches in which it matched nothing.
    """
    kw = " ".join(keyword.lower().split())
    if len(kw) > 2 and kw.startswith('"') and kw.endswith('"'):
        phrase = kw[1:-1].replace('"', "").strip()
        return bool(phrase) and phrase in text
    words = kw.replace('"', "").replace("(", "").replace(")", "").split()
    return bool(words) and all(w in text for w in words)


def keyword_hits(posts: list[RedditPostData], keywords: list[str]) -> dict[str, int]:
    """How many of `posts` each configured keyword matches, with an explicit 0 for none.

    Computed from the posts rather than from the provider's queries, so it means the same thing
    whichever provider ran and however it grouped the keywords into searches.
    """
    texts = [f"{p.title}\n{p.body}".lower() for p in posts]
    return {k: sum(keyword_matches(k, t) for t in texts) for k in keywords}


def previous_searches(run: AgentRun) -> list[dict]:
    """Stats of this project's earlier searches of the same run kind, newest first."""
    limit = max(ZERO_YIELD_RUNS, KEYWORD_HISTORY_RUNS) - 1
    return list(AgentRun.objects.filter(project=run.project, kind=run.kind, stats__has_key="fetched")
                .exclude(pk=run.pk).order_by("-created_at").values_list("stats", flat=True)[:limit])


def check_search_yield(reporter: RunReporter, fetched: int, by_keyword: dict[str, int],
                       history: list[dict]) -> None:
    """Report a search that keeps finding nothing, which a successful run would otherwise hide.

    A provider or query problem looks like a quiet day: the search succeeds and returns nothing.
    One empty search is normal; `ZERO_YIELD_RUNS` in a row is reported as an error (a Sentry
    issue). Keywords that matched nothing in each of the last `KEYWORD_HISTORY_RUNS` searches are
    a warning, worth tuning; when they are most of the keywords, the searches themselves are
    probably failing, so that is an error too.

    Args:
        fetched: Posts this search returned.
        by_keyword: This search's matches per keyword (`keyword_hits`).
        history: Earlier searches' stats, newest first (`previous_searches`).
    """
    earlier = history[: ZERO_YIELD_RUNS - 1]
    if fetched == 0:
        if len(earlier) == ZERO_YIELD_RUNS - 1 and all(h.get("fetched") == 0 for h in earlier):
            message = f"The last {ZERO_YIELD_RUNS} searches found no posts at all"
            reporter.error(f"{message}. The search is probably failing, not just quiet",
                           exc=SearchYieldError(message), runs=ZERO_YIELD_RUNS)
        return  # every keyword is at 0 too; flagging each of them would only repeat this
    windows = [by_keyword] + [h["by_keyword"] for h in history if isinstance(h.get("by_keyword"), dict)]
    windows = windows[:KEYWORD_HISTORY_RUNS]
    if len(windows) < KEYWORD_HISTORY_RUNS:
        return
    # Only keywords present in every window: one added since then hasn't had its chance yet.
    tracked = [k for k in by_keyword if all(k in w for w in windows)]
    dead = [k for k in tracked if all(w[k] == 0 for w in windows)]
    if not dead:
        return
    message = f"{len(dead)} of {len(tracked)} keywords matched no posts in the last {KEYWORD_HISTORY_RUNS} searches"
    data = {"dead_keywords": dead, "runs": KEYWORD_HISTORY_RUNS}
    if len(dead) >= 2 and len(dead) * 2 > len(tracked):
        reporter.error(f"{message}. The searches are probably failing for them",
                       exc=SearchYieldError("Most keywords matched no posts"), **data)
    else:
        reporter.warning(message, **data)


# --- Scoring ----------------------------------------------------------------------------


def post_variables(post: RedditPost) -> dict:
    """Prompt variables for scoring a post: the post, the author role and the selection learnings.

    The batch and sync scoring paths both build their input here, so the learnings reach a
    scheduled run exactly as they reach "Run now". Long bodies are cut at `BODY_CHAR_LIMIT`.
    """
    body = post.body[:BODY_CHAR_LIMIT] + ("\n[…truncated]" if len(post.body) > BODY_CHAR_LIMIT else "")
    age_hours = None
    if post.posted_at:
        age_hours = max(0, int((timezone.now() - post.posted_at).total_seconds() // 3600))
    return {
        "subreddit": post.subreddit, "title": post.title, "body": body, "upvotes": post.upvotes,
        "num_comments": post.num_comments, "flair": post.flair, "age_hours": age_hours,
        "author_role": policy_for(post.project).author_role,
        "learnings_selection": selection_learnings(post.project, AgentType.REDDIT),
    }


def apply_score(post: RedditPost, parsed, call) -> None:
    post.relevance_score = max(0, min(100, parsed.score))
    post.relevance_reason = parsed.reason
    post.reply_worthwhile = parsed.reply_worthwhile
    post.score_status = RedditPost.ScoreStatus.SCORED
    post.score_error = ""
    post.scored_at = timezone.now()
    post.score_call = call
    post.save()


def fail_score(post: RedditPost, error: str, call=None) -> None:
    post.score_status = RedditPost.ScoreStatus.FAILED
    post.score_error = error[:2000]
    post.score_call = call
    post.save()


TOP_SCORES_REPORTED = 10
SCORE_BANDS = ((0, 24), (25, 49), (50, 74), (75, 100))


def report_scores(reporter, posts: list[RedditPost]) -> None:
    """One summary event for a scoring pass, whichever path produced it.

    Identifiers and scores only. `reason` is the model's rationale rather than post content,
    and it is truncated here: the full text already lives on RedditPost.relevance_reason.
    """
    scored = [p for p in posts if p.score_status == RedditPost.ScoreStatus.SCORED]
    failed = sum(p.score_status == RedditPost.ScoreStatus.FAILED for p in posts)
    top = sorted(scored, key=lambda p: -(p.relevance_score or 0))[:TOP_SCORES_REPORTED]
    reporter.event(
        f"Scored {len(scored)} of {len(posts)} posts",
        scored=len(scored), failed=failed,
        distribution={f"{lo}-{hi}": sum(lo <= (p.relevance_score or 0) <= hi for p in scored)
                      for lo, hi in SCORE_BANDS},
        top=[{"reddit_id": p.reddit_id, "subreddit": p.subreddit, "score": p.relevance_score,
              "reply_worthwhile": p.reply_worthwhile, "reason": (p.relevance_reason or "")[:200]}
             for p in top],
    )


def score_sync(run, reporter, posts: list[RedditPost]) -> None:
    reporter.step(f"Scoring {len(posts)} posts")
    last_exc = None
    for post in posts:
        try:
            result = llm.complete("reddit.score", post_variables(post), project=run.project, run=run)
            apply_score(post, result.parsed, result.call)
        except llm.LLMError as exc:
            fail_score(post, str(exc), exc.call)
            last_exc = exc
    failed = sum(p.score_status == RedditPost.ScoreStatus.FAILED for p in posts)
    if failed:
        # One report for the batch, not one per post: they fail for the same reason.
        reporter.error(f"{failed} post(s) couldn't be scored", exc=last_exc)
    report_scores(reporter, posts)


def submit_scoring_batch(run, reporter, posts: list[RedditPost]) -> None:
    b = llm_batch.submit("reddit.score", [(f"post-{p.pk}", post_variables(p)) for p in posts],
                         project=run.project, run=run)
    run.status = AgentRun.Status.WAITING_BATCH
    run.params = {**run.params, "batch_id": b.pk}
    run.save(update_fields=["status", "params"])
    reporter.step(f"Scoring {len(posts)} posts in a batch (usually a few minutes)")
    from .tasks import poll_scoring_batch

    poll_scoring_batch.apply_async((run.pk,), countdown=settings.LLM_BATCH_POLL_SECONDS)


def apply_batch_results(run, reporter, b: LLMBatch) -> list[RedditPost]:
    results = llm_batch.collect(b)
    posts = {f"post-{p.pk}": p for p in RedditPost.objects.filter(project=run.project, first_seen_run=run)}
    for cid, r in results.items():
        post = posts.get(cid)
        if post is None:
            continue
        if r.ok:
            apply_score(post, r.parsed, r.call)
        else:
            fail_score(post, r.error, r.call)
    failed = sum(not r.ok for r in results.values())
    if failed:
        reporter.error(f"{failed} post(s) couldn't be scored")
    scored_posts = list(posts.values())
    report_scores(reporter, scored_posts)
    return scored_posts


# --- Drafting ---------------------------------------------------------------------------


def comment_variables(post: RedditPost, project: Project, *, previous: str = "", instruction: str = "") -> dict:
    """Prompt variables for drafting a reply: the post, the user's custom instructions, the
    writing learnings and any feedback the digest hasn't folded in yet.

    Args:
        previous: The current draft body, when revising one.
        instruction: The revision direction (preset nudge text plus the user's instruction).
    """
    return {**post_variables(post), **learning_variables(project, AgentType.REDDIT),
            "project_name": project.name, "reason": post.relevance_reason,
            "guidance": load_config(project).guidance.strip(),
            "previous_draft": previous, "instruction": instruction}


def comment_content(parsed: RedditComment) -> dict:
    """The draft content to store from a comment response (`RedditCommentContent` shape)."""
    return {"body": parsed.body, "poster_read": parsed.poster_read.strip()}


def draft_replies(run: AgentRun, reporter: RunReporter, cfg: RedditAgentConfig, posts: list[RedditPost]) -> None:
    """Draft a reply for every scored post at or above the threshold that's worth one.

    Reports the candidates it considered, then one step per draft. A post that fails to draft is
    reported with its exception and skipped; the rest still get drafts.

    Args:
        posts: This run's posts, scored or not; unscored and already-drafted posts are skipped.
    """
    candidates = [
        p for p in posts
        if p.score_status == RedditPost.ScoreStatus.SCORED and p.reply_worthwhile
        and p.relevance_score >= cfg.relevance_threshold and not p.drafts.exists()
    ]
    scored = sum(p.score_status == RedditPost.ScoreStatus.SCORED for p in posts)
    run.stats.update(scored=scored, above_threshold=len(candidates), threshold=cfg.relevance_threshold)
    run.save(update_fields=["stats"])
    model_key, model = draft_model_for(run.project, AgentType.REDDIT)
    reporter.event(
        f"{len(candidates)} of {scored} scored posts are worth a reply (threshold {cfg.relevance_threshold})",
        scored=scored, above_threshold=len(candidates), threshold=cfg.relevance_threshold, draft_model=model_key,
        candidates=[{"reddit_id": p.reddit_id, "subreddit": p.subreddit, "score": p.relevance_score}
                    for p in sorted(candidates, key=lambda p: -p.relevance_score)],
    )
    drafted = 0
    for post in sorted(candidates, key=lambda p: -p.relevance_score):
        reporter.step(f"Drafting a reply in r/{post.subreddit}: {post.title[:60]}")
        try:
            result = llm.complete("reddit.comment", comment_variables(post, run.project), project=run.project, run=run,
                                  model=model)
        except llm.LLMError as exc:
            reporter.error(f"Couldn't draft a reply for “{post.title[:60]}”: {exc}", exc=exc)
            continue
        draft = services.create_draft(run.project, agent_type=AgentType.REDDIT, kind=DraftKind.REDDIT_COMMENT,
                                      content=comment_content(result.parsed), result=result, run=run,
                                      source_reddit_post=post)
        compliance.lint(draft, run)
        drafted += 1
    run.stats["drafted"] = drafted
    run.save(update_fields=["stats"])
    reporter.success(f"Drafted {drafted} repl{'y' if drafted == 1 else 'ies'}")


# --- Entry points -----------------------------------------------------------------------


def research_posts(run: AgentRun, reporter: RunReporter) -> list[RedditPost]:
    """Fetch and score fresh posts for the Content Agent's topic research. Drafts no replies.

    The posts are stored as found by topic research, so the next Reddit run takes over the
    reply-worthy ones (`take_over_research_posts`). Scoring is synchronous: the content run
    needs the scores before it can propose topics.

    Returns:
        The new posts, scored. Empty when Reddit isn't configured or nothing new was found.

    Raises:
        RuntimeError: The search failed and returned no posts at all.
    """
    cfg = load_config(run.project)
    if not cfg.subreddits or not cfg.keywords:
        return []
    posts = fetch(run, reporter, cfg, found_by=RedditPost.FoundBy.TOPIC_RESEARCH)
    if posts:
        score_sync(run, reporter, posts)
    return posts


def take_over_research_posts(run: AgentRun, reporter: RunReporter) -> list[RedditPost]:
    """Claim the posts topic research scored since the last Reddit run, so they get replies too.

    Each post is claimed once (`handoff_run`), and only once its scoring has finished. Both the
    sync and the batch path call this before drafting, so neither leaves them behind.
    """
    claimable = RedditPost.objects.filter(
        project=run.project, found_by=RedditPost.FoundBy.TOPIC_RESEARCH, handoff_run__isnull=True,
    ).exclude(score_status=RedditPost.ScoreStatus.PENDING)
    ids = list(claimable.values_list("pk", flat=True))
    RedditPost.objects.filter(pk__in=ids, handoff_run__isnull=True).update(handoff_run=run)
    posts = list(RedditPost.objects.filter(pk__in=ids, handoff_run=run))
    if posts:
        run.stats["carried_over"] = len(posts)
        run.save(update_fields=["stats"])
        reporter.event(f"Took over {len(posts)} post(s) found by topic research", carried_over=len(posts),
                       reddit_ids=[p.reddit_id for p in posts])
    return posts


def run_reddit_agent(run: AgentRun, reporter: RunReporter) -> None:
    """Fetch, score (in a batch for scheduled runs), then draft replies, including for posts
    topic research found since the last run.

    Raises:
        ValueError: The Reddit Agent has no subreddits or keywords.
    """
    cfg = load_config(run.project)
    if not cfg.subreddits or not cfg.keywords:
        raise ValueError("Add at least one subreddit and one keyword to the Reddit Agent config")
    posts = fetch(run, reporter, cfg)
    if posts and run.trigger == AgentRun.Trigger.SCHEDULED and cfg.batch_scheduled_scoring:
        submit_scoring_batch(run, reporter, posts)
        return
    if posts:
        score_sync(run, reporter, posts)
    carried = take_over_research_posts(run, reporter)
    if not posts and not carried:
        reporter.success("No new posts since the last scan")
        return
    draft_replies(run, reporter, cfg, posts + carried)


def finish_batch_run(run: AgentRun, reporter: RunReporter) -> None:
    """Apply a finished scoring batch, then draft replies as the sync path does."""
    b = LLMBatch.objects.get(pk=run.params["batch_id"])
    reporter.step("Collecting batch scores")
    posts = apply_batch_results(run, reporter, b)
    carried = take_over_research_posts(run, reporter)
    draft_replies(run, reporter, load_config(run.project), posts + carried)


def batch_expired(run: AgentRun) -> bool:
    b = LLMBatch.objects.get(pk=run.params["batch_id"])
    return timezone.now() - b.submitted_at > timedelta(hours=settings.LLM_BATCH_MAX_AGE_HOURS)


def regenerate(draft: Draft, nudge: str, instruction: str, run: AgentRun) -> DraftVersion:
    """Write a new AI version of a Reddit draft, steered by a nudge and/or an instruction.

    Uses the same prompt variables as a first draft, so the custom instructions and learnings
    apply to regenerations too. The new version is linted for compliance.

    Args:
        nudge: A key of `NUDGES`, or "".
        instruction: The user's own direction, or "".
        run: The `regenerate_draft` run the LLM call is billed to.

    Returns:
        The new current version.

    Raises:
        ValueError: The draft has no source post to reply to.
    """
    post = draft.source_reddit_post
    if post is None:
        raise ValueError("This draft has no source post")
    text = nudge_instruction(nudge, instruction, draft.project.name)
    variables = comment_variables(post, draft.project, previous=draft.current_version.content["body"],
                                  instruction=text)
    _, model = draft_model_for(draft.project, AgentType.REDDIT)
    result = llm.complete("reddit.comment", variables, project=draft.project, run=run, model=model)
    version = services.add_version(draft, comment_content(result.parsed), source=DraftVersion.Source.AI_REGENERATED,
                                   result=result, nudge=nudge, instruction=instruction)
    compliance.lint(draft, run)
    return version
