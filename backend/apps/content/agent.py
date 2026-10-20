from apps.agents.registry import AgentSpec, register

from .config import ContentAgentConfig
from .pipeline import regenerate, run_content_agent

register(AgentSpec(
    agent_type="content",
    label="Content Agent",
    config_model=ContentAgentConfig,
    run=run_content_agent,
    regenerate=regenerate,
    default_schedule={"kind": "weekly", "day": 1, "time": "09:00"},  # Mondays
))
