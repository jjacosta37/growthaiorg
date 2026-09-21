"""Compliance lint: a cheap model check against the hard rules, plus deterministic checks.
Flags are shown on the draft; they never block it (a human reviews everything anyway)."""

import logging
import re

import llm
from apps.policy.service import policy_for

from .content import as_text
from .models import Draft

log = logging.getLogger(__name__)

COMMUNITY_KINDS = {"reddit_comment"}


def has_disclosure(text: str, author_role: str) -> bool:
    words = [re.escape(w) for w in author_role.lower().split() if len(w) > 2]
    pattern = r"\b(disclosure|i (built|made|work on|run|work at)"
    if words:
        pattern += "|" + r"\s+".join(words)
    pattern += r")\b"
    return re.search(pattern, text, re.I) is not None


def deterministic_flags(draft: Draft, text: str) -> list[dict]:
    """Checks that don't need a model: a community post that names the product must disclose affiliation."""
    policy = policy_for(draft.project)
    if draft.kind not in COMMUNITY_KINDS or not any(r["id"] == "missing_disclosure" for r in policy.rules):
        return []
    name = draft.project.name
    if re.search(rf"\b{re.escape(name)}\b", text, re.I) and not has_disclosure(text, policy.author_role):
        return [{"rule": "missing_disclosure", "excerpt": name,
                 "explanation": f"Mentions {name} without the disclosure: {policy.rendered_disclosure()}"}]
    return []


def lint(draft: Draft, run=None) -> list[dict]:
    content = draft.current_version.content
    text = as_text(draft.kind, content)
    flags = deterministic_flags(draft, text)
    try:
        result = llm.complete("compliance.lint", {"kind": draft.kind, "text": text}, project=draft.project, run=run)
        deterministic_rules = {f["rule"] for f in flags}
        flags += [f.model_dump() for f in result.parsed.flags if f.rule not in deterministic_rules]
    except llm.LLMError as exc:
        # Never blocks the draft, but it must not be invisible either: without the run
        # warning the only trace of a failed lint was a line in the worker's stdout.
        log.warning("compliance lint failed for draft %s: %s", draft.pk, exc, exc_info=True)
        if run is not None:
            from apps.agents.runs import RunReporter  # local: apps.agents imports apps.inbox

            RunReporter(run).warning(f"Compliance lint failed for draft {draft.pk}: {exc}", exc=exc)
    draft.compliance_flags = flags
    draft.save(update_fields=["compliance_flags", "updated_at"])
    return flags
