"""Each agent registers its config schema and pipeline entry points here. The generic tasks,
scheduler and API dispatch through the registry, so adding an agent never touches them."""

from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic import BaseModel


@dataclass(frozen=True)
class AgentSpec:
    agent_type: str
    label: str
    config_model: type[BaseModel]
    run: Callable  # (run, reporter) -> None
    regenerate: Callable  # (draft, nudge, instruction, run) -> DraftVersion
    # A builder schedule (apps.agents.schedule), in the project's timezone.
    default_schedule: dict = field(default_factory=lambda: {"kind": "every_hours", "hours": 6, "minute": 0})


_agents: dict[str, AgentSpec] = {}


def register(spec: AgentSpec) -> AgentSpec:
    _agents[spec.agent_type] = spec
    return spec


def get(agent_type: str) -> AgentSpec:
    try:
        return _agents[agent_type]
    except KeyError:
        raise KeyError(f"Unknown agent {agent_type!r}") from None


def all_agents() -> list[AgentSpec]:
    order = ["reddit", "content", "x"]
    return sorted(_agents.values(), key=lambda s: order.index(s.agent_type) if s.agent_type in order else 99)
