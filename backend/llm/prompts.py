"""Versioned prompt files.

Layout: prompts/<task path>/v<N>.md, where task "reddit.score" lives in prompts/reddit/score/.
Each file is YAML frontmatter followed by two Jinja sections:

    ---
    model_tier: fast          # fast | writer  (mapped via settings.LLM_MODELS)
    max_tokens: 1024
    effort: medium            # optional; omit for Haiku (it rejects effort)
    schema: RelevanceScore    # optional; name registered in llm.schemas
    tools: [web_search]       # optional
    include_context: true     # prepend guardrails + context docs (default true)
    ---
    === system ===
    Task instructions...
    === user ===
    The {{ variable }} message...

The latest version is used unless a version is pinned. Never edit a version that has produced
drafts; add v<N+1> instead, so every draft's recorded prompt version stays meaningful.
"""

import hashlib
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml
from django.conf import settings
from jinja2 import Environment, StrictUndefined

_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.S)
_SECTIONS = re.compile(r"^=== (system|user) ===$", re.M)
_VERSION_FILE = re.compile(r"^v(\d+)\.md$")
_jinja = Environment(undefined=StrictUndefined, keep_trailing_newline=False, autoescape=False)

VALID_TIERS = {"fast", "writer"}
VALID_TOOLS = {"web_search"}
MAX_NON_STREAMING_TOKENS = 16000


class PromptError(Exception):
    pass


@dataclass(frozen=True)
class PromptSpec:
    task: str
    version: str
    model_tier: str
    max_tokens: int
    system_template: str
    user_template: str
    hash: str
    effort: str | None = None
    schema: str | None = None
    tools: tuple[str, ...] = field(default_factory=tuple)
    include_context: bool = True
    web_search_max_uses: int = 5

    def render(self, variables: dict) -> tuple[str, str]:
        system = _jinja.from_string(self.system_template).render(**variables).strip()
        user = _jinja.from_string(self.user_template).render(**variables).strip()
        return system, user


def prompts_dir() -> Path:
    return Path(settings.PROMPTS_DIR)


def task_dir(task: str) -> Path:
    if not re.fullmatch(r"[a-z0-9_]+(\.[a-z0-9_]+)*", task):
        raise PromptError(f"Invalid task name {task!r}")
    return prompts_dir().joinpath(*task.split("."))


def available_versions(task: str) -> list[int]:
    d = task_dir(task)
    if not d.is_dir():
        return []
    return sorted(int(m.group(1)) for p in d.iterdir() if (m := _VERSION_FILE.match(p.name)))


def load_prompt(task: str, version: str | None = None) -> PromptSpec:
    if version is None:
        versions = available_versions(task)
        if not versions:
            raise PromptError(f"No prompt files for task {task!r} in {task_dir(task)}")
        version = f"v{versions[-1]}"
    path = task_dir(task) / f"{version}.md"
    if not path.is_file():
        raise PromptError(f"Prompt {task} {version} not found at {path}")
    return _parse(task, version, path.read_text(encoding="utf-8"))


def _parse(task: str, version: str, raw: str) -> PromptSpec:
    m = _FRONTMATTER.match(raw)
    if not m:
        raise PromptError(f"{task} {version}: missing YAML frontmatter")
    meta = yaml.safe_load(m.group(1)) or {}
    body = m.group(2)

    parts = _SECTIONS.split(body)
    # parts = [preamble, "system", text, "user", text]
    sections = dict(zip(parts[1::2], parts[2::2], strict=True))
    if "user" not in sections:
        raise PromptError(f"{task} {version}: missing '=== user ===' section")

    tier = meta.get("model_tier")
    if tier not in VALID_TIERS:
        raise PromptError(f"{task} {version}: model_tier must be one of {sorted(VALID_TIERS)}")
    max_tokens = int(meta.get("max_tokens", 4096))
    if max_tokens > MAX_NON_STREAMING_TOKENS:
        raise PromptError(f"{task} {version}: max_tokens > {MAX_NON_STREAMING_TOKENS} needs streaming")
    tools = tuple(meta.get("tools") or ())
    if unknown := set(tools) - VALID_TOOLS:
        raise PromptError(f"{task} {version}: unknown tools {sorted(unknown)}")

    return PromptSpec(
        task=task,
        version=version,
        model_tier=tier,
        max_tokens=max_tokens,
        effort=meta.get("effort"),
        schema=meta.get("schema"),
        tools=tools,
        include_context=bool(meta.get("include_context", True)),
        web_search_max_uses=int(meta.get("web_search_max_uses", 5)),
        system_template=sections.get("system", "").strip(),
        user_template=sections["user"].strip(),
        hash=hashlib.sha256(raw.encode()).hexdigest()[:16],
    )


@lru_cache(maxsize=1)
def guardrails_text() -> str:
    """Hard content rules included in every call that uses context (fintech compliance)."""
    return (prompts_dir() / "_system" / "guardrails.md").read_text(encoding="utf-8").strip()
