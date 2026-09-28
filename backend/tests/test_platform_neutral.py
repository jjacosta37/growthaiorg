"""Luka is a platform for any company. Active prompts, the guardrails and application code must not
bake in any customer or industry; industry specifics belong in policies/*.yaml (data)."""

import re
from pathlib import Path

import pytest
from django.conf import settings

from llm.prompts import available_versions

# Industry-specific terms that must never appear outside policy packs.
BANNED = [
    r"fintech", r"\binvest", r"\bretire", r"\broth\b", r"\b401\(?k", r"\birs\b", r"portfolio", r"financial",
    r"\bstocks?\b", r"crypto", r"advisor", r"\btax(es)?\b", r"investment returns", r"\bus-focused",
    r"medical", r"\bdiagnos", r"patients?\b",
]


def banned_hits(text: str) -> list[str]:
    text = text.lower()
    return [pat for pat in BANNED if re.search(pat, text)]


def active_prompt_files():
    root = Path(settings.PROMPTS_DIR)
    for d in sorted({p.parent for p in root.rglob("v*.md")}):
        task = ".".join(d.relative_to(root).parts)
        yield d / f"v{available_versions(task)[-1]}.md"
    yield root / "_system" / "guardrails.md"


@pytest.mark.parametrize("path", list(active_prompt_files()), ids=lambda p: str(p.relative_to(p.parents[2])))
def test_active_prompts_are_industry_neutral(path):
    hits = banned_hits(path.read_text())
    assert not hits, f"{path.name} contains {hits}; move industry specifics into a policy pack"


def test_application_code_is_industry_neutral():
    root = Path(settings.BASE_DIR)
    offenders = {}
    for p in root.rglob("*.py"):
        if {"tests", "migrations"} & set(p.parts):
            continue
        if hits := banned_hits(p.read_text()):
            offenders[str(p.relative_to(root))] = hits
    assert offenders == {}
