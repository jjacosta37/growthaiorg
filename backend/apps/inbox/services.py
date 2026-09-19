"""Draft lifecycle. Agents create drafts here; the API calls the actions."""

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from .content import validate_content
from .models import Draft, DraftVersion


class DraftStateError(Exception):
    pass


@transaction.atomic
def add_version(draft: Draft, content: dict, *, source: str, result=None, nudge: str = "",
                instruction: str = "") -> DraftVersion:
    """Validate and append a version, and make it current. `result` is an llm.LLMResult for AI versions."""
    content = validate_content(draft.kind, content)
    n = (draft.versions.aggregate(m=Max("n"))["m"] or 0) + 1
    version = DraftVersion.objects.create(
        draft=draft, n=n, source=source, content=content, nudge=nudge, instruction=instruction,
        prompt_name=result.task if result else "", prompt_version=result.prompt_version if result else "",
        model=result.model if result else "", llm_call=result.call if result else None,
    )
    draft.current_version = version
    draft.save(update_fields=["current_version", "updated_at"])
    return version


@transaction.atomic
def create_draft(project, *, agent_type: str, kind: str, content: dict, result, run=None,
                 source_reddit_post=None, blog_topic=None) -> Draft:
    draft = Draft.objects.create(project=project, agent_type=agent_type, kind=kind, agent_run=run,
                                 source_reddit_post=source_reddit_post, blog_topic=blog_topic)
    add_version(draft, content, source=DraftVersion.Source.AI_INITIAL, result=result)
    return draft


def edit(draft: Draft, content: dict) -> DraftVersion:
    """Save a human edit. Partial content is merged onto the current version (e.g. edit just a title)."""
    _require_new(draft, "edit")
    merged = {**draft.current_version.content, **content}
    return add_version(draft, merged, source=DraftVersion.Source.HUMAN_EDIT)


def mark_read(draft: Draft) -> None:
    if draft.read_at is None:
        draft.read_at = timezone.now()
        draft.save(update_fields=["read_at", "updated_at"])


def mark_posted(draft: Draft, posted_url: str = "") -> None:
    if draft.status == Draft.Status.POSTED:
        return
    draft.status = Draft.Status.POSTED
    draft.posted_at = timezone.now()
    draft.posted_url = posted_url
    draft.read_at = draft.read_at or draft.posted_at
    draft.save(update_fields=["status", "posted_at", "posted_url", "read_at", "updated_at"])


def dismiss(draft: Draft, reason: str, note: str = "") -> None:
    _require_new(draft, "dismiss")
    draft.status = Draft.Status.DISMISSED
    draft.dismiss_reason = reason
    draft.dismiss_note = note
    draft.read_at = draft.read_at or timezone.now()
    draft.save(update_fields=["status", "dismiss_reason", "dismiss_note", "read_at", "updated_at"])


def restore(draft: Draft) -> None:
    """Undo a dismiss or mark-posted (misclicks happen)."""
    draft.status = Draft.Status.NEW
    draft.dismiss_reason = ""
    draft.dismiss_note = ""
    draft.posted_at = None
    draft.posted_url = ""
    draft.save(update_fields=["status", "dismiss_reason", "dismiss_note", "posted_at", "posted_url", "updated_at"])


def _require_new(draft: Draft, action: str) -> None:
    if draft.status != Draft.Status.NEW:
        raise DraftStateError(f"Can't {action} a draft that is {draft.status}")
