from apps.agents.registry import AgentSpec, register

from .config import XAgentConfig
from .pipeline import regenerate, run_x_agent

register(AgentSpec(
    agent_type="x",
    label="X Agent",
    config_model=XAgentConfig,
    run=run_x_agent,
    regenerate=regenerate,
    default_schedule={"kind": "weekdays", "days": [1, 2, 3, 4, 5], "times": ["14:00"]},
))
