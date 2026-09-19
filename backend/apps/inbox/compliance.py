"""Compliance lint: a cheap model check against the hard rules, plus deterministic checks.
Flags are shown on the draft; they never block it (a human reviews everything anyway)."""

import logging
import re

import llm

from .content import as_text
from .models import Draft

log = logging.getLogger(__name__)

DISCLOSURE = re.compile(r"\b(founder|co-?founder|i (built|made|work on|run))\b", re.I)


def deterministic_flags(draft: Draft, text: str) -> list[dict]:
    flags = []
    name = draft.project.name
    mentions = re.search(rf"\b{re.escape(name)}\b", text, re.I)
    if draft.kind == "reddit_comment" and mentions and not DISCLOSURE.search(text):
        flags.append({"rule": "missing_disclosure", "excerpt": name,
                      "explanation": f"Mentions {name} without disclosing you're the founder."})
    return flags


def lint(draft: Draft, run=None) -> list[dict]:
    content = draft.current_version.content
    text = as_text(draft.kind, content)
    flags = deterministic_flags(draft, text)
    try:
        result = llm.complete("compliance.lint", {"kind": draft.kind, "text": text}, project=draft.project, run=run)
        deterministic_rules = {f["rule"] for f in flags}
        flags += [f.model_dump() for f in result.parsed.flags if f.rule not in deterministic_rules]
    except llm.LLMError as exc:
        log.warning("compliance lint failed for draft %s: %s", draft.pk, exc)
    draft.compliance_flags = flags
    draft.save(update_fields=["compliance_flags", "updated_at"])
    return flags
