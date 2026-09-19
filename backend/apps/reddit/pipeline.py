"""Reddit Agent: search → dedupe → score relevance → draft replies for the best posts."""

from datetime import timedelta

from django.conf import settings
from django.utils import timezone

import llm
from apps.agents.models import AgentConfig, AgentRun, AgentType, ExternalUsage
from apps.agents.runs import RunReporter
from apps.inbox import compliance, services
from apps.inbox.models import Draft, DraftKind, DraftVersion
from apps.inbox.nudges import nudge_instruction
from llm import batch as llm_batch
from llm.models import LLMBatch
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
    reporter.step(f"Reddit Agent scanning {preview}")
    source = get_source()
    result = source.search(RedditSearch(subreddits=subs, keywords=cfg.keywords, time_window=cfg.time_window,
                                        max_posts=cfg.max_posts_per_run, include_nsfw=cfg.include_nsfw))
    if result.provider == "apify":
        ExternalUsage.objects.create(
            project=run.project, agent_run=run, provider="apify", purpose="reddit_search",
            resource_id=result.resource_id, external_run_id=result.external_run_id, items=len(result.posts),
            cost_usd=result.cost_usd, error=result.error,
        )
    if result.error and not result.posts:
        raise RuntimeError(f"Reddit search failed: {result.error}")
    if result.error:
        reporter.warning(f"Reddit search had a problem (continuing with {len(result.posts)} posts): {result.error}")
    new, dupes = store_new_posts(run.project, run, result.posts)
    run.stats.update(fetched=len(result.posts), new_posts=len(new), duplicates=dupes)
    run.save(update_fields=["stats"])
    reporter.event(f"Found {len(result.posts)} posts, {len(new)} new")
    return new


# --- Scoring ----------------------------------------------------------------------------


def post_variables(post: RedditPost) -> dict:
    body = post.body[:BODY_CHAR_LIMIT] + ("\n[…truncated]" if len(post.body) > BODY_CHAR_LIMIT else "")
    age_hours = None
    if post.posted_at:
        age_hours = max(0, int((timezone.now() - post.posted_at).total_seconds() // 3600))
    return {
        "subreddit": post.subreddit, "title": post.title, "body": body, "upvotes": post.upvotes,
        "num_comments": post.num_comments, "flair": post.flair, "age_hours": age_hours,
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


def score_sync(run, reporter, posts: list[RedditPost]) -> None:
    reporter.step(f"Scoring {len(posts)} posts")
    for post in posts:
        try:
            result = llm.complete("reddit.score", post_variables(post), project=run.project, run=run)
            apply_score(post, result.parsed, result.call)
        except llm.LLMError as exc:
            fail_score(post, str(exc), exc.call)
    failed = sum(p.score_status == RedditPost.ScoreStatus.FAILED for p in posts)
    if failed:
        reporter.error(f"{failed} post(s) couldn't be scored")


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
    return list(posts.values())


# --- Drafting ---------------------------------------------------------------------------


def comment_variables(post: RedditPost, project, *, previous: str = "", instruction: str = "") -> dict:
    return {**post_variables(post), "project_name": project.name, "reason": post.relevance_reason,
            "previous_draft": previous, "instruction": instruction}


def draft_replies(run, reporter, cfg: RedditAgentConfig, posts: list[RedditPost]) -> None:
    candidates = [
        p for p in posts
        if p.score_status == RedditPost.ScoreStatus.SCORED and p.reply_worthwhile
        and p.relevance_score >= cfg.relevance_threshold and not p.drafts.exists()
    ]
    scored = sum(p.score_status == RedditPost.ScoreStatus.SCORED for p in posts)
    run.stats.update(scored=scored, above_threshold=len(candidates), threshold=cfg.relevance_threshold)
    run.save(update_fields=["stats"])
    reporter.event(
        f"{len(candidates)} of {scored} scored posts are worth a reply (threshold {cfg.relevance_threshold})"
    )
    drafted = 0
    for post in sorted(candidates, key=lambda p: -p.relevance_score):
        reporter.step(f"Drafting a reply in r/{post.subreddit}: {post.title[:60]}")
        try:
            result = llm.complete("reddit.comment", comment_variables(post, run.project), project=run.project, run=run)
        except llm.LLMError as exc:
            reporter.error(f"Couldn't draft a reply for “{post.title[:60]}”: {exc}")
            continue
        draft = services.create_draft(run.project, agent_type=AgentType.REDDIT, kind=DraftKind.REDDIT_COMMENT,
                                      content={"body": result.parsed.body}, result=result, run=run,
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


def regenerate(draft: Draft, nudge: str, instruction: str, run) -> DraftVersion:
    post = draft.source_reddit_post
    if post is None:
        raise ValueError("This draft has no source post")
    text = nudge_instruction(nudge, instruction, draft.project.name)
    variables = comment_variables(post, draft.project, previous=draft.current_version.content["body"],
                                  instruction=text)
    result = llm.complete("reddit.comment", variables, project=draft.project, run=run)
    version = services.add_version(draft, {"body": result.parsed.body}, source=DraftVersion.Source.AI_REGENERATED,
                                   result=result, nudge=nudge, instruction=instruction)
    compliance.lint(draft, run)
    return version
