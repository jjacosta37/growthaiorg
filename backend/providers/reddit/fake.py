"""Deterministic RedditSource for tests and for local dev without Apify (REDDIT_SOURCE=fake)."""

from datetime import UTC, datetime, timedelta

from .base import RedditPostData, RedditSearch, RedditSearchResult


class FakeRedditSource:
    name = "fake"

    def __init__(self, posts: list[RedditPostData] | None = None):
        self.posts = posts
        self.queries: list[RedditSearch] = []

    def search(self, query: RedditSearch) -> RedditSearchResult:
        self.queries.append(query)
        posts = self.posts if self.posts is not None else sample_posts(query)
        kept = posts[: query.max_posts]
        # The reporting fields are filled in too, so the run trail a test asserts on has the
        # same shape as a real one.
        return RedditSearchResult(
            posts=kept, provider=self.name, status="SUCCEEDED", duration_ms=1,
            items_raw=len(posts), queries=len(query.subreddits) or 1,
        )


def sample_posts(query: RedditSearch) -> list[RedditPostData]:
    now = datetime.now(UTC)
    subs = query.subreddits or ["smallbusiness"]
    kws = query.keywords or ["getting started"]
    return [
        RedditPostData(
            reddit_id=f"fake{i}", subreddit=subs[i % len(subs)],
            title=f"Question about {kws[i % len(kws)]}", body=f"I'm trying to understand {kws[i % len(kws)]}. Help?",
            url=f"https://www.reddit.com/r/{subs[i % len(subs)]}/comments/fake{i}/", author=f"user{i}",
            upvotes=i * 3, num_comments=i, posted_at=now - timedelta(hours=i),
        )
        for i in range(5)
    ]
