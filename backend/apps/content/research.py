"""Topic research: the audience questions the Reddit Agent has found, as evidence for topics.

A post is evidence when it scored at or above the Reddit relevance threshold in the last 30 days
and doesn't already back a topic (rejected topics included). When there is none, the run fetches
and scores fresh posts first, without drafting replies.
"""

import html
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone
from pydantic import ValidationError

from apps.agents.models import AgentRun
from apps.agents.runs import RunReporter
from apps.core.models import Project
from apps.reddit.config import RedditAgentConfig
from apps.reddit.models import RedditPost
from apps.reddit.pipeline import load_config as load_reddit_config
from apps.reddit.pipeline import research_posts

WINDOW_DAYS = 30
MAX_POSTS = 60  # bounds the topics prompt: the most relevant posts go in, the rest wait
EXCERPT_CHARS = 500


def relevant_posts(project: Project, threshold: int) -> list[RedditPost]:
    """The project's unused evidence: scored at or above `threshold` in the last 30 days, most
    relevant first, and not already behind any topic."""
    since = timezone.now() - timedelta(days=WINDOW_DAYS)
    return list(
        RedditPost.objects.filter(project=project, score_status=RedditPost.ScoreStatus.SCORED,
                                  relevance_score__gte=threshold, blog_topics__isnull=True)
        .filter(Q(posted_at__gte=since) | Q(posted_at__isnull=True, fetched_at__gte=since))
        .order_by("-relevance_score", "-posted_at")[:MAX_POSTS]
    )


def reddit_config(reporter: RunReporter, project: Project) -> RedditAgentConfig | None:
    """The Reddit config, or None (reported) if it no longer validates."""
    try:
        return load_reddit_config(project)
    except ValidationError as exc:
        reporter.warning("Reddit Agent settings are invalid; topics proposed without Reddit evidence", exc=exc)
        return None


def gather_evidence(run: AgentRun, reporter: RunReporter) -> list[RedditPost]:
    """The posts to propose topics from, fetching fresh ones first if there are none.

    Never fails the run: when Reddit isn't configured, nothing relevant turns up or the fetch
    fails, the run reports why and topics are proposed without Reddit evidence.
    """
    cfg = reddit_config(reporter, run.project)
    if cfg is None:
        return []
    posts = relevant_posts(run.project, cfg.relevance_threshold)
    if not posts:
        if not cfg.subreddits or not cfg.keywords:
            return no_evidence(run, reporter, "reddit_not_configured",
                               "No Reddit evidence used: the Reddit Agent has no subreddits or keywords")
        try:
            research_posts(run, reporter)
        except RuntimeError as exc:
            reporter.warning(f"Topic research on Reddit failed, continuing without it: {exc}", exc=exc)
            return no_evidence(run, reporter, "research_failed", "No Reddit evidence used: the Reddit search failed")
        posts = relevant_posts(run.project, cfg.relevance_threshold)
        if not posts:
            return no_evidence(run, reporter, "nothing_relevant",
                               "No Reddit evidence used: no relevant posts found")
    run.stats["posts_considered"] = len(posts)
    run.save(update_fields=["stats"])
    reporter.event(f"Using {len(posts)} Reddit post(s) as evidence", posts_considered=len(posts),
                   threshold=cfg.relevance_threshold, window_days=WINDOW_DAYS, cap=MAX_POSTS,
                   reddit_ids=[p.reddit_id for p in posts])
    return posts


def no_evidence(run: AgentRun, reporter: RunReporter, reason: str, message: str) -> list[RedditPost]:
    """Report why no Reddit evidence is used on this run."""
    run.stats.update(posts_considered=0, no_evidence_reason=reason)
    run.save(update_fields=["stats"])
    reporter.event(message, posts_considered=0, reason=reason)
    return []


def prompt_posts(posts: list[RedditPost]) -> list[dict]:
    """The posts as prompt variables: third-party text, escaped so it can't close its delimiters."""
    def esc(text: str) -> str:
        return html.escape(text, quote=True)

    items = []
    for p in posts:
        body = " ".join(p.body.split())
        excerpt = body[:EXCERPT_CHARS] + ("…" if len(body) > EXCERPT_CHARS else "")
        items.append({"id": p.pk, "subreddit": esc(p.subreddit), "title": esc(p.title), "excerpt": esc(excerpt)})
    return items
