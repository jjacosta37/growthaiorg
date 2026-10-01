from typing import Literal

from pydantic import BaseModel, Field, field_validator


class RedditAgentConfig(BaseModel):
    """The Reddit Agent's settings, edited on its agent page. Every call multiplier is bounded."""

    subreddits: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    relevance_threshold: int = Field(70, ge=0, le=100)
    max_posts_per_run: int = Field(40, ge=1, le=200)
    time_window: Literal["hour", "day", "week"] = "day"
    include_nsfw: bool = False
    # Scheduled runs score via the Message Batches API (50% cheaper, results in minutes to hours).
    # "Run now" always scores synchronously.
    batch_scheduled_scoring: bool = True
    # The user's own standing instructions, given to every reply (below the content rules).
    guidance: str = Field("", max_length=2000, description="Custom instructions for every reply")

    @field_validator("subreddits")
    @classmethod
    def clean_subreddits(cls, v):
        return list(dict.fromkeys(s.strip().removeprefix("r/").strip("/") for s in v if s.strip()))

    @field_validator("keywords")
    @classmethod
    def clean_keywords(cls, v):
        return list(dict.fromkeys(k.strip() for k in v if k.strip()))
