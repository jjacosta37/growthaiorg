import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

MAX_SUBREDDITS = 20
MAX_KEYWORDS = 30
MAX_KEYWORD_CHARS = 80
SUBREDDIT_NAME = re.compile(r"^[A-Za-z0-9_]{2,21}$")


class RedditAgentConfig(BaseModel):
    """The Reddit Agent's settings, edited on its agent page.

    The search runs once per subreddit and keyword query, so the counts and lengths here are what
    bound a run's Apify spend, alongside the actor's per-run charge cap (docs/security-patterns.md §11).
    """

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
    def clean_subreddits(cls, v: list[str]) -> list[str]:
        """Normalise `r/name` forms, dedupe, and enforce Reddit's name format and the count limit."""
        names = list(dict.fromkeys(s.strip().removeprefix("r/").strip("/") for s in v if s.strip()))
        if bad := [n for n in names if not SUBREDDIT_NAME.match(n)]:
            raise ValueError(f"Not a valid subreddit name: {bad[0][:40]}")
        if len(names) > MAX_SUBREDDITS:
            raise ValueError(f"At most {MAX_SUBREDDITS} subreddits")
        return names

    @field_validator("keywords")
    @classmethod
    def clean_keywords(cls, v: list[str]) -> list[str]:
        """Dedupe and enforce the count and length limits."""
        keywords = list(dict.fromkeys(" ".join(k.split()) for k in v if k.strip()))
        if any(len(k) > MAX_KEYWORD_CHARS for k in keywords):
            raise ValueError(f"Keywords are at most {MAX_KEYWORD_CHARS} characters")
        if len(keywords) > MAX_KEYWORDS:
            raise ValueError(f"At most {MAX_KEYWORDS} keywords")
        return keywords
