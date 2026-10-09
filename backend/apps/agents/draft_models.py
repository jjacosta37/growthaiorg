"""Which model an agent drafts with.

A project stores a key of `settings.LLM_DRAFT_MODELS` per agent; this module decides which keys a
project may use and turns a stored key into a model ID. Subscription gating belongs in
`available_draft_models`, the one place that answers "may this project use this model".
"""

from typing import TYPE_CHECKING

from django.conf import settings

from .models import AgentConfig

if TYPE_CHECKING:
    from apps.core.models import Project


def available_draft_models(project: "Project") -> list[str]:
    """Keys of `settings.LLM_DRAFT_MODELS` this project may pick, in display order.

    Every key for now; this is where plan-based gating will go.
    """
    return list(settings.LLM_DRAFT_MODELS)


def draft_model_options(project: "Project") -> list[dict[str, str]]:
    """The selector's options for this project: `[{key, label}]`."""
    return [{"key": key, "label": settings.LLM_DRAFT_MODELS[key]["label"]} for key in available_draft_models(project)]


def effective_draft_key(project: "Project", stored: str) -> str:
    """The key to use for a stored choice, falling back to the default when it isn't allowed.

    A key can stop being allowed (removed from settings, or later a downgraded plan); a run then
    drafts with the default instead of failing.
    """
    if stored in settings.LLM_DRAFT_MODELS and stored in available_draft_models(project):
        return stored
    return settings.LLM_DRAFT_MODEL_DEFAULT


def draft_model_for(project: "Project", agent_type: str) -> tuple[str, str]:
    """The (key, model ID) an agent drafts with for this project."""
    key = effective_draft_key(project, AgentConfig.for_project(project, agent_type).draft_model)
    return key, settings.LLM_DRAFT_MODELS[key]["model"]
