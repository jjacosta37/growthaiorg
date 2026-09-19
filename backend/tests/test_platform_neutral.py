"""Sift is a platform: OpenWealth is one customer. The active prompts and the guardrails must not
bake in any customer or industry. Industry specifics belong in policies/*.yaml (data)."""

import re
from pathlib import Path

import pytest
from django.conf import settings

from llm.prompts import available_versions

BANNED = [
    r"openwealth", r"fintech", r"\binvest", r"\bretire", r"\broth\b", r"\b401", r"\birs\b", r"portfolio",
    r"financial", r"\bstock", r"crypto", r"advisor", r"\btax", r"investment returns", r"\bus-focused",
]


def active_prompt_files():
    root = Path(settings.PROMPTS_DIR)
    tasks = {p.parent for p in root.rglob("v*.md")}
    for d in sorted(tasks):
        task = ".".join(d.relative_to(root).parts)
        yield d / f"v{available_versions(task)[-1]}.md"
    yield root / "_system" / "guardrails.md"


@pytest.mark.parametrize("path", list(active_prompt_files()), ids=lambda p: str(p.relative_to(p.parents[2])))
def test_active_prompts_are_industry_neutral(path):
    text = path.read_text().lower()
    hits = [pat for pat in BANNED if re.search(pat, text)]
    assert not hits, f"{path.name} contains {hits}; move industry specifics into a policy pack"


def test_code_has_no_customer_name():
    root = Path(settings.BASE_DIR)
    offenders = [
        str(p.relative_to(root)) for p in root.rglob("*.py")
        if "tests" not in p.parts and "migrations" not in p.parts and "openwealth" in p.read_text().lower()
    ]
    assert offenders == []
