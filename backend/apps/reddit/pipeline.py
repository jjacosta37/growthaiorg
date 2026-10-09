"""Reddit Agent: search → dedupe → score relevance → draft replies for the best posts."""

from collections import Counter
from datetime import timedelta

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
from providers.reddit import ApifyRedditSource, FakeRedditSource, RedditSearch

from .config import RedditAgentConfig
from .models import RedditPost

BODY_CHAR_LIMIT = 6000  # long posts are truncated for scoring/drafting (noted in the prompt input)


def get_source():
    if settings.REDDIT_SOURCE == "fake":
        return FakeRedditSource()
    if not settings.APIFY_TOKEN:
        raise RuntimeError("APIFY_TOKEN is not set (or set REDDIT_SOURCE=fake for local testing)")
    return ApifyRedditSource(settings.APIFY_TOKEN, settings.APIFY_REDDIT_ACTOR)


def load_config(project) -> RedditAgentConfig:
    return RedditAgentConfig.model_validate(AgentConfig.for_project(project, AgentType.REDDIT).config)


# --- Fetch + dedupe ---------------------------------------------------------------------


def store_new_posts(project, run, posts) -> tuple[list[RedditPost], int]:
    """Insert posts we haven't seen before. Returns (new posts, duplicates skipped)."""
    ids = [p.reddit_id for p in posts]
    known = set(RedditPost.objects.filter(project=project, reddit_id__in=ids).values_list("reddit_id", flat=True))
    new, seen = [], set()
    for p in posts:
        if p.reddit_id in known or p.reddit_id in seen:
            continue
        seen.add(p.reddit_id)
        new.append(RedditPost(
            project=project, reddit_id=p.reddit_id, subreddit=p.subreddit, title=p.title, body=p.body,
            url=p.url, author=p.author, upvotes=p.upvotes, num_comments=p.num_comments, flair=p.flair,
            posted_at=p.posted_at, first_seen_run=run,
        ))
    # ignore_conflicts guards against a concurrent run inserting the same post
    RedditPost.objects.bulk_create(new, ignore_conflicts=True)
    new_ids = [p.reddit_id for p in new]
    stored = list(RedditPost.objects.filter(project=project, first_seen_run=run, reddit_id__in=new_ids))
    return stored, len(posts) - len(stored)


def fetch(run: AgentRun, reporter: RunReporter, cfg: RedditAgentConfig) -> list[RedditPost]:
    subs = cfg.subreddits
    preview = ", ".join(f"r/{s}" for s in subs[:2]) + (f" +{len(subs) - 2} more" if len(subs) > 2 else "")
    reporter.step(f"Reddit Agent scanning {preview}", subreddits=subs, keywords=cfg.keywords,
                  time_window=cfg.time_window, max_posts=cfg.max_posts_per_run)
    source = get_source()
    result = source.search(RedditSearch(subreddits=subs, keywords=cfg.keywords, time_window=cfg.time_window,
                                        max_posts=cfg.max_posts_per_run, include_nsfw=cfg.include_nsfw))
    if result.provider == "apify":
        seconds = round(result.duration_ms / 1000, 1)
        record_external(
            run, reporter, provider="apify", purpose="reddit_search", resource_id=result.resource_id,
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
    new, dupes = store_new_posts(run.project, run, result.posts)
    run.stats.update(fetched=len(result.posts), new_posts=len(new), duplicates=dupes)
    run.save(update_fields=["stats"])
    # Counted here rather than in the adapter: which subreddits produced nothing is the fact
    # this step used to hide, and it must not depend on which provider ran the search.
    by_subreddit = Counter(p.subreddit for p in result.posts)
    reporter.event(f"Found {len(result.posts)} posts, {len(new)} new",
                   fetched=len(result.posts), new_posts=len(new), duplicates=dupes,
                   queries=result.queries,
                   by_subreddit={s: by_subreddit.get(s.strip().removeprefix("r/"), 0) for s in subs})
    return new


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


def run_reddit_agent(run: AgentRun, reporter: RunReporter) -> None:
    cfg = load_config(run.project)
    if not cfg.subreddits or not cfg.keywords:
        raise ValueError("Add at least one subreddit and one keyword to the Reddit Agent config")
    posts = fetch(run, reporter, cfg)
    if not posts:
        reporter.success("No new posts since the last scan")
        return
    if run.trigger == AgentRun.Trigger.SCHEDULED and cfg.batch_scheduled_scoring:
        submit_scoring_batch(run, reporter, posts)
        return
    score_sync(run, reporter, posts)
    draft_replies(run, reporter, cfg, posts)


def finish_batch_run(run: AgentRun, reporter: RunReporter) -> None:
    b = LLMBatch.objects.get(pk=run.params["batch_id"])
    reporter.step("Collecting batch scores")
    posts = apply_batch_results(run, reporter, b)
    draft_replies(run, reporter, load_config(run.project), posts)


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
