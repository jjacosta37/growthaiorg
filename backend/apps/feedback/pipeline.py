"""Folds new feedback into an agent's learnings digest."""

from django.utils import timezone

import llm
from apps.agents import registry
from apps.agents.runs import RunReporter
from apps.policy.service import policy_for

from .models import AgentFeedback, AgentLearnings
from .services import feedback_line, pending

DIGEST_BATCH_LIMIT = 100  # entries folded in per call; the rest wait for the next run
EXCERPT_CHARS = 300


def entry_variables(entry: AgentFeedback) -> dict:
    """An entry as the digest sees it: the feedback plus a short excerpt of the draft it was on,
    so a comment like "too long" can be generalized. The excerpt goes to the model only."""
    content = entry.draft_version.content if entry.draft_version_id and entry.draft_version else {}
    body = content.get("body") or " ".join(content.get("posts", [])) or content.get("body_md", "")
    excerpt = body[:EXCERPT_CHARS] + ("…" if len(body) > EXCERPT_CHARS else "")
    return {**feedback_line(entry), "excerpt": excerpt}


def digest_feedback(run, reporter: RunReporter) -> None:
    project, agent_type = run.project, run.params["agent_type"]
    rebuild = bool(run.params.get("rebuild"))
    learnings = AgentLearnings.for_project(project, agent_type)
    if rebuild:
        # From scratch: the newest entries, since older lessons are the ones newer feedback overrides.
        qs = AgentFeedback.objects.filter(project=project, agent_type=agent_type).order_by("-created_at")
    else:
        qs = pending(project, agent_type).order_by("created_at")  # the rest wait for the next run
    entries = list(qs.select_related("draft__source_reddit_post", "draft_version")[:DIGEST_BATCH_LIMIT])
    # Oldest first, so "newer wins" in the prompt matches the order the model reads.
    entries.sort(key=lambda e: e.created_at)
    if not entries:
        if rebuild:  # every entry was deleted: nothing left to learn from
            learnings.writing_md = learnings.selection_md = ""
            learnings.source = AgentLearnings.Source.AI
            learnings.save()
            reporter.success("Learnings cleared: there is no feedback left")
        else:
            reporter.success("No new feedback to learn from")
        return
    reporter.step(f"{'Rebuilding' if rebuild else 'Updating'} learnings from {len(entries)} feedback "
                  f"entr{'y' if len(entries) == 1 else 'ies'}", entries=len(entries), rebuild=rebuild)
    keep_previous = not rebuild
    result = llm.complete("feedback.digest", {
        "project_name": project.name, "author_role": policy_for(project).author_role,
        "agent_label": registry.get(agent_type).label,
        "previous_writing": learnings.writing_md if keep_previous else "",
        "previous_selection": learnings.selection_md if keep_previous else "",
        "previous_is_human": keep_previous and learnings.source == AgentLearnings.Source.HUMAN,
        "entries": [entry_variables(e) for e in entries],
    }, project=project, run=run)
    learnings.writing_md = result.parsed.writing.strip()
    learnings.selection_md = result.parsed.selection.strip()
    learnings.source = AgentLearnings.Source.AI
    learnings.save()
    AgentFeedback.objects.filter(pk__in=[e.pk for e in entries]).update(digested_at=timezone.now())
    run.stats.update(entries=len(entries), rebuild=rebuild)
    run.save(update_fields=["stats"])
    reporter.success(f"Learnings updated from {len(entries)} feedback entr{'y' if len(entries) == 1 else 'ies'}",
                     entries=len(entries), feedback_ids=[e.pk for e in entries],
                     writing_chars=len(learnings.writing_md), selection_chars=len(learnings.selection_md))
