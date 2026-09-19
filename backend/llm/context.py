"""Builds the cached system prefix shared by every task: guardrails + the project's context docs.

Prompt caching is a byte-exact prefix match, so this block must be deterministic: a fixed
document order and no timestamps or IDs. It goes first in `system` with a cache_control
breakpoint, and the task-specific instructions come after it. Caches are per model, so the
fast and writer tiers each warm their own copy.
"""

from collections.abc import Callable

# (project) -> list of (title, markdown) in a stable order. Registered by apps.context.
_context_provider: Callable | None = None


def set_context_provider(fn: Callable) -> None:
    global _context_provider
    _context_provider = fn


def context_documents(project) -> list[tuple[str, str]]:
    if project is None or _context_provider is None:
        return []
    return _context_provider(project)


def render_context_block(project) -> str:
    from .prompts import guardrails_text

    parts = [guardrails_text()]
    docs = context_documents(project)
    if docs:
        parts.append("# Context documents\n\nWhat we know about the product. Treat these as ground truth.")
        for title, body in docs:
            parts.append(f'<document title="{title}">\n{body.strip()}\n</document>')
    return "\n\n".join(parts)


def build_system(project, task_system: str, include_context: bool) -> list[dict]:
    blocks: list[dict] = []
    if include_context:
        blocks.append(
            {"type": "text", "text": render_context_block(project), "cache_control": {"type": "ephemeral"}}
        )
    if task_system:
        blocks.append({"type": "text", "text": task_system})
    return blocks
