"""Feedback capture and the variables prompts read. Pipelines call `learning_variables`; the inbox
and agent APIs call `record`."""

import logging

from django.conf import settings
from django.db import transaction

from .models import AgentFeedback, AgentLearnings

log = logging.getLogger(__name__)

RECENT_FEEDBACK_LIMIT = 20  # undigested entries passed raw to a prompt, newest first
FEEDBACK_TEXT_LIMIT = 2000


def record(draft, *, source: str, text: str = "", rating: str = "") -> AgentFeedback:
    """Store feedback on a draft and schedule the digest. Coalesces bursts: the digest task
    runs after a short delay and folds in every entry that is still undigested."""
    entry = AgentFeedback.objects.create(
        project=draft.project, agent_type=draft.agent_type, draft=draft, draft_version=draft.current_version,
        source=source, rating=rating, text=text.strip()[:FEEDBACK_TEXT_LIMIT],
    )
    log.info("feedback %s recorded for draft %s (project %s, %s, source=%s)",
             entry.pk, draft.pk, draft.project_id, draft.agent_type, source)
    transaction.on_commit(lambda: schedule_digest(draft.project_id, draft.agent_type))
    return entry


def schedule_digest(project_id: int, agent_type: str, *, rebuild: bool = False) -> None:
    from .tasks import digest_feedback_task

    digest_feedback_task.apply_async((project_id, agent_type), {"rebuild": rebuild},
                                     countdown=0 if rebuild else settings.FEEDBACK_DIGEST_DELAY_SECONDS)


def pending(project, agent_type: str):
    return AgentFeedback.objects.filter(project=project, agent_type=agent_type, digested_at__isnull=True)


def feedback_line(entry: AgentFeedback) -> dict:
    """What a prompt sees of one entry: where it came from and what was said. No draft text."""
    post = entry.draft.source_reddit_post if entry.draft_id and entry.draft else None
    return {
        "rating": entry.rating, "text": entry.text, "source": entry.source,
        "where": f"r/{post.subreddit}: {post.title[:120]}" if post else "",
    }


def learning_variables(project, agent_type: str) -> dict:
    """{learnings_writing, learnings_selection, recent_feedback} for a prompt. Empty when the
    user has given no feedback, so prompts render exactly as before."""
    learnings = AgentLearnings.objects.filter(project=project, agent_type=agent_type).first()
    recent = pending(project, agent_type).select_related("draft__source_reddit_post")[:RECENT_FEEDBACK_LIMIT]
    return {
        "learnings_writing": learnings.writing_md.strip() if learnings else "",
        "learnings_selection": learnings.selection_md.strip() if learnings else "",
        "recent_feedback": [feedback_line(e) for e in recent],
    }


def selection_learnings(project, agent_type: str) -> str:
    """Just the selection lessons, for scoring (one query per post, no feedback lookups)."""
    selection = (AgentLearnings.objects.filter(project=project, agent_type=agent_type)
                 .values_list("selection_md", flat=True).first())
    return (selection or "").strip()
