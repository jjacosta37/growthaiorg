"""LangSmith integration. Tracing turns on when LANGSMITH_TRACING=true and LANGSMITH_API_KEY is set."""

from django.conf import settings
from langsmith import traceable
from langsmith.run_helpers import get_current_run_tree


def wrap_client(client):
    if not settings.LANGSMITH_TRACING:
        return client
    from langsmith.wrappers import wrap_anthropic

    return wrap_anthropic(client)


def current_run_id() -> str:
    if not settings.LANGSMITH_TRACING:
        return ""
    run = get_current_run_tree()
    return str(run.id) if run is not None else ""


__all__ = ["traceable", "wrap_client", "current_run_id"]
