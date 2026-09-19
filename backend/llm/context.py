"""Builds the cached system prefix shared by every task: guardrails + the project's context docs.

Prompt caching is a byte-exact prefix match, so this block must be deterministic: a fixed
document order and no timestamps or IDs. It goes first in `system` with a cache_control
breakpoint, and the task-specific instructions come after it. Caches are per model, so the
fast and writer tiers each warm their own copy.
"""

from collections.abc import Callable

# (project) -> list of (title, markdown) in a stable order. Registered by apps.context.
_context_provider: Callable | None = None
# (project) -> guardrail variables {project_name, author_role, rules, disclosure, blog_disclaimer}.
# Registered by apps.policy.
_policy_provider: Callable | None = None

GENERIC_GUARDRAILS = {"project_name": "the product", "author_role": "team", "rules": [], "disclosure": "",
                      "blog_disclaimer": ""}


def set_context_provider(fn: Callable) -> None:
    global _context_provider
    _context_provider = fn


def set_policy_provider(fn: Callable) -> None:
    global _policy_provider
    _policy_provider = fn


def guardrail_variables(project) -> dict:
    if project is None or _policy_provider is None:
        return dict(GENERIC_GUARDRAILS)
    return _policy_provider(project)


def context_documents(project) -> list[tuple[str, str]]:
    if project is None or _context_provider is None:
        return []
    return _context_provider(project)


def render_context_block(project, *, include_guardrails: bool = True, include_docs: bool = True) -> str:
    from .prompts import render_guardrails

    parts = [render_guardrails(guardrail_variables(project))] if include_guardrails else []
    docs = context_documents(project) if include_docs else []
    if docs:
        parts.append("# Context documents\n\nWhat we know about the product. Treat these as ground truth.")
        for title, body in docs:
            parts.append(f'<document title="{title}">\n{body.strip()}\n</document>')
    return "\n\n".join(parts)


def build_system(
    project,
    task_system: str,
    *,
    include_guardrails: bool = True,
    include_context: bool = True,
    extra_cached: str | None = None,
) -> list[dict]:
    """[guardrails + context docs] [extra_cached] [task instructions].

    The cache breakpoint goes on the last stable block. `extra_cached` holds large inputs that
    several calls in a row share (e.g. crawled pages during onboarding), so they're cached too.
    """
    stable: list[dict] = []
    shared = render_context_block(project, include_guardrails=include_guardrails, include_docs=include_context)
    if shared:
        stable.append({"type": "text", "text": shared})
    if extra_cached:
        stable.append({"type": "text", "text": extra_cached})
    if stable:
        stable[-1]["cache_control"] = {"type": "ephemeral"}
    if task_system:
        stable.append({"type": "text", "text": task_system})
    return stable
