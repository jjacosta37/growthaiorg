"""LangSmith integration. Tracing turns on when LANGSMITH_TRACING=true and LANGSMITH_API_KEY is set."""

import logging
import types
from contextlib import contextmanager

from django.conf import settings
from langsmith import traceable
from langsmith.run_helpers import get_current_run_tree

log = logging.getLogger(__name__)


def _add_completions_shim(client) -> None:
    """Give the client a dummy `completions` so LangSmith can wrap it.

    langsmith's wrap_anthropic assigns `client.completions.create` unconditionally, but
    the anthropic 1.x SDK dropped the legacy Text Completions API, so the attribute is
    gone and the wrap raises AttributeError. (It guards `client.beta.messages` with
    hasattr a few lines later; `completions` was missed.)

    We only ever call `messages.create`, which is wrapped separately, so a placeholder
    here costs nothing: langsmith overwrites its `create` and nothing calls it. Remove
    this once langsmith guards that attribute.
    """
    if not hasattr(client, "completions"):
        client.completions = types.SimpleNamespace(create=lambda *a, **kw: None)


def wrap_client(client):
    """Wrap the Anthropic client for tracing, or return it untouched.

    Tracing is observability: it must never be the reason a pipeline run fails. If the
    wrap breaks — a langsmith/anthropic version mismatch, say — we log and carry on
    with an unwrapped client rather than taking the run down with us.
    """
    if not settings.LANGSMITH_TRACING:
        return client

    try:
        from langsmith.wrappers import wrap_anthropic

        _add_completions_shim(client)
        return wrap_anthropic(client)
    except Exception:
        log.warning("LangSmith tracing is on but the client couldn't be wrapped; "
                    "continuing untraced", exc_info=True)
        return client


@contextmanager
def trace_group(name: str, *, run_type: str = "chain", metadata: dict | None = None,
                inputs: dict | None = None):
    """A parent span that every traced call inside becomes a child of.

    Without one, each llm.complete() is its own root trace and a run's calls scatter across
    LangSmith. This is the equivalent of the sequence node LangGraph puts around a graph.

    Only creating the span is guarded: if the body raises, that is the pipeline's exception
    and it must propagate (langsmith records it on the span on the way out).
    """
    if not settings.LANGSMITH_TRACING:
        yield None
        return

    try:
        from langsmith import trace

        span = trace(name=name, run_type=run_type, inputs=inputs or {}, metadata=metadata or {})
    except Exception:
        log.warning("couldn't open the LangSmith span %r; continuing untraced", name, exc_info=True)
        yield None
        return

    with span as run_tree:
        yield run_tree


@contextmanager
def trace_tool(name: str, *, inputs: dict | None = None, metadata: dict | None = None):
    """A child span for non-LLM work (Apify, crawling). Yields a dict to fill with outputs.

    Sibling of trace_group with the same fail-safe contract, but run_type="tool", so an
    external call shows up in the trace tree next to the LLM calls instead of being the
    invisible gap before them.

    `tree.end()` is deliberately skipped when the body raises: that is the caller's
    exception, and langsmith records it on the span on the way out.
    """
    outputs: dict = {}
    with trace_group(name, run_type="tool", inputs=inputs, metadata=metadata) as tree:
        yield outputs
        if tree is not None:
            try:
                tree.end(outputs=outputs)
            except Exception:
                log.warning("couldn't record outputs on the LangSmith span %r", name, exc_info=True)


def current_run_id() -> str:
    if not settings.LANGSMITH_TRACING:
        return ""
    run = get_current_run_tree()
    return str(run.id) if run is not None else ""


__all__ = ["traceable", "wrap_client", "current_run_id", "trace_group", "trace_tool"]
