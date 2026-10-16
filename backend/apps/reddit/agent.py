from apps.agents.registry import AgentSpec, register

from .config import RedditAgentConfig
from .pipeline import regenerate, run_reddit_agent

register(AgentSpec(
    agent_type="reddit",
    label="Reddit Agent",
    config_model=RedditAgentConfig,
    run=run_reddit_agent,
    regenerate=regenerate,
    default_schedule={"kind": "every_hours", "hours": 4, "minute": 0},
))
