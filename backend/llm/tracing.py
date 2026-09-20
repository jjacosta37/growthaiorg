"""LangSmith integration. Tracing turns on when LANGSMITH_TRACING=true and LANGSMITH_API_KEY is set."""

import logging
import types

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


def current_run_id() -> str:
    if not settings.LANGSMITH_TRACING:
        return ""
    run = get_current_run_tree()
    return str(run.id) if run is not None else ""


__all__ = ["traceable", "wrap_client", "current_run_id"]
