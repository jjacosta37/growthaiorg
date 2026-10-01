"""Feedback capture and the variables prompts read. Pipelines call `learning_variables`; the inbox
and agent APIs call `record`."""

import html
import logging

from django.conf import settings
from django.db import transaction
from django.db.models import QuerySet

from apps.core.models import Project
from apps.inbox.models import Draft

from .models import AgentFeedback, AgentLearnings

log = logging.getLogger(__name__)

RECENT_FEEDBACK_LIMIT = 20  # undigested entries passed raw to a prompt, newest first
FEEDBACK_TEXT_LIMIT = 2000


def record(draft: Draft, *, source: str, text: str = "", rating: str = "") -> AgentFeedback:
    """Store feedback on a draft and schedule the digest.

    Bursts coalesce: the digest task runs after a short delay and folds in every entry that is
    still undigested, so ten quick comments cost one digest call.

    Args:
        draft: The draft the feedback is about; the entry takes its project and agent type, and
            pins its current version so the digest sees what was actually written.
        source: An `AgentFeedback.Source` value.
        text: The user's comment, stripped and truncated to `FEEDBACK_TEXT_LIMIT`.
        rating: An `AgentFeedback.Rating` value, or "" for none.

    Returns:
        The stored entry.
    """
    entry = AgentFeedback.objects.create(
        project=draft.project, agent_type=draft.agent_type, draft=draft, draft_version=draft.current_version,
        source=source, rating=rating, text=text.strip()[:FEEDBACK_TEXT_LIMIT],
    )
    log.info("feedback %s recorded for draft %s (project %s, %s, source=%s)",
             entry.pk, draft.pk, draft.project_id, draft.agent_type, source)
    transaction.on_commit(lambda: schedule_digest(draft.project_id, draft.agent_type))
    return entry


def schedule_digest(project_id: int, agent_type: str) -> None:
    """Queue a digest of the pending feedback after `FEEDBACK_DIGEST_DELAY_SECONDS`."""
    from .tasks import digest_feedback_task

    digest_feedback_task.apply_async((project_id, agent_type), countdown=settings.FEEDBACK_DIGEST_DELAY_SECONDS)


def pending(project: Project, agent_type: str) -> QuerySet[AgentFeedback]:
    """Feedback the digest hasn't folded in yet."""
    return AgentFeedback.objects.filter(project=project, agent_type=agent_type, digested_at__isnull=True)


def tag_safe(text: str) -> str:
    """Escape text placed inside a prompt's delimiter tags, so it can't close them."""
    return html.escape(text, quote=True)


def feedback_line(entry: AgentFeedback) -> dict:
    """What a drafting prompt sees of one entry: the rating and the user's own words. Nothing from
    the post it was on: third-party text stays out of the system prompt."""
    return {"rating": entry.rating, "text": tag_safe(entry.text), "source": entry.source}


def learning_variables(project: Project, agent_type: str) -> dict:
    """The learnings and pending feedback, as variables for a drafting prompt.

    Returns:
        `{learnings_writing, learnings_selection, recent_feedback}`. All empty when the user has
        given no feedback, so prompts render exactly as they did before feedback existed.
    """
    learnings = AgentLearnings.objects.filter(project=project, agent_type=agent_type).first()
    recent = pending(project, agent_type)[:RECENT_FEEDBACK_LIMIT]
    return {
        "learnings_writing": learnings.writing_md.strip() if learnings else "",
        "learnings_selection": learnings.selection_md.strip() if learnings else "",
        "recent_feedback": [feedback_line(e) for e in recent],
    }


def selection_learnings(project: Project, agent_type: str) -> str:
    """Just the selection lessons, for scoring (one query per post, no feedback lookups)."""
    selection = (AgentLearnings.objects.filter(project=project, agent_type=agent_type)
                 .values_list("selection_md", flat=True).first())
    return (selection or "").strip()
