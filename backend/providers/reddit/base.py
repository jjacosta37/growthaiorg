"""Reddit data source interface. Pipelines depend on this, not on Apify, so the official Reddit
API (or anything else) can be swapped in later without touching pipeline logic."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol

TimeWindow = Literal["hour", "day", "week", "month"]


@dataclass
class RedditPostData:
    reddit_id: str  # base36 id without the "t3_" prefix
    subreddit: str  # without "r/"
    title: str
    body: str
    url: str
    author: str
    upvotes: int
    num_comments: int
    posted_at: datetime | None
    flair: str = ""


@dataclass
class RedditSearch:
    subreddits: list[str]
    keywords: list[str]
    time_window: TimeWindow = "day"
    max_posts: int = 50
    include_nsfw: bool = False


@dataclass
class RedditSearchResult:
    posts: list[RedditPostData] = field(default_factory=list)
    provider: str = ""
    resource_id: str = ""
    external_run_id: str = ""
    cost_usd: Decimal = Decimal(0)
    error: str = ""
    # Reported on the run so a search is not an opaque gap. `items_raw` is what the provider
    # returned before mapping, dedupe and truncation; `queries` is how many searches it took,
    # which the pipeline can't work out for itself without knowing the provider's query syntax.
    status: str = ""
    duration_ms: int = 0
    items_raw: int = 0
    queries: int = 0


class RedditSource(Protocol):
    name: str

    def search(self, query: RedditSearch) -> RedditSearchResult:
        """Recent posts in any of `subreddits` matching any of `keywords`, newest first."""
        ...
