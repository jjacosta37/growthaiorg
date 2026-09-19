"""RedditSource backed by the harshmaur/reddit-scraper Apify actor.

One actor run covers every subreddit: we pass Reddit search URLs (restrict_sr=1, sort=new,
OR-joined keywords) as startUrls instead of one run per subreddit, since each run has a
start fee. Verified against a live run on 2026-09-19.
"""

import logging
import math
from datetime import datetime, timedelta
from decimal import Decimal
from urllib.parse import urlencode

from .base import RedditPostData, RedditSearch, RedditSearchResult

log = logging.getLogger(__name__)

MAX_QUERY_CHARS = 400  # Reddit rejects very long search queries; split keywords across URLs


def search_term(keyword: str) -> str:
    """Reddit search syntax for one keyword. Recall beats precision here (scoring filters later):
    - `rebalancing`            → rebalancing
    - `roth conversion`        → (roth conversion)   all words, any order
    - `"allocation drift"`     → "allocation drift"  exact phrase, only when I quote it myself
    Exact-phrase matching on every keyword returned 0 posts in a live test; grouped words didn't."""
    kw = " ".join(keyword.split())
    if len(kw) > 2 and kw.startswith('"') and kw.endswith('"'):
        inner = kw[1:-1].replace('"', "").strip()
        return f'"{inner}"' if inner else ""
    kw = kw.replace('"', "").replace("(", "").replace(")", "").strip()
    return f"({kw})" if " " in kw else kw


def keyword_queries(keywords: list[str]) -> list[str]:
    """OR-joined search terms, split into queries that stay under MAX_QUERY_CHARS."""
    queries, current = [], []
    for term in filter(None, (search_term(k) for k in keywords)):
        if current and len(" OR ".join([*current, term])) > MAX_QUERY_CHARS:
            queries.append(" OR ".join(current))
            current = []
        current.append(term)
    if current:
        queries.append(" OR ".join(current))
    return queries


def search_urls(query: RedditSearch) -> list[str]:
    urls = []
    for sub in query.subreddits:
        sub = sub.strip().removeprefix("r/").strip("/")
        for q in keyword_queries(query.keywords):
            params = urlencode({"q": q, "restrict_sr": 1, "sort": "new", "t": query.time_window})
            urls.append(f"https://www.reddit.com/r/{sub}/search/?{params}")
    return urls


def _parse_dt(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def map_item(item: dict) -> RedditPostData | None:
    if item.get("dataType") != "post":
        return None
    reddit_id = (item.get("parsedId") or str(item.get("id") or "").removeprefix("t3_")).strip()
    if not reddit_id:
        return None
    return RedditPostData(
        reddit_id=reddit_id,
        subreddit=(item.get("parsedCommunityName") or str(item.get("communityName") or "").removeprefix("r/")),
        title=item.get("title") or "",
        body=item.get("body") or "",
        url=item.get("postUrl") or item.get("contentUrl") or "",
        author=item.get("authorName") or "",
        upvotes=int(item.get("upVotes") or 0),
        num_comments=int(item.get("commentsCount") or 0),
        posted_at=_parse_dt(item.get("createdAt")),
        flair=item.get("flair") or "",
    )


class ApifyRedditSource:
    name = "apify"

    def __init__(self, token: str, actor_id: str = "harshmaur/reddit-scraper", *, timeout_minutes: int = 15,
                 client=None):
        if client is None:
            from apify_client import ApifyClient

            client = ApifyClient(token)
        self.client = client
        self.actor_id = actor_id
        self.timeout = timedelta(minutes=timeout_minutes)

    def build_input(self, query: RedditSearch) -> dict:
        urls = search_urls(query)
        return {
            "startUrls": [{"url": u} for u in urls],
            # The actor's cap isn't a hard total (a live run returned 10 posts for a cap of 6),
            # so cap per URL roughly and enforce the real limit after mapping.
            "maxPostsCount": max(5, math.ceil(query.max_posts / max(len(urls), 1))),
            "crawlCommentsPerPost": False,
            "includeNSFW": query.include_nsfw,
        }

    def search(self, query: RedditSearch) -> RedditSearchResult:
        result = RedditSearchResult(provider=self.name, resource_id=self.actor_id)
        if not query.subreddits or not query.keywords:
            return result
        try:
            run = self.client.actor(self.actor_id).call(run_input=self.build_input(query), run_timeout=self.timeout)
        except Exception as exc:  # network/auth/actor failure: surface it on the run
            log.warning("apify reddit search failed: %s", exc)
            result.error = f"{type(exc).__name__}: {exc}"
            return result
        if run is None:
            result.error = "Apify run did not finish in time"
            return result
        result.external_run_id = run.id or ""
        result.cost_usd = Decimal(str(run.usage_total_usd or 0))
        if run.status != "SUCCEEDED":
            result.error = f"Apify run {run.id} ended with status {run.status}"
        seen: set[str] = set()
        posts = []
        for item in self.client.dataset(run.default_dataset_id).iterate_items():
            post = map_item(item)
            if post and post.reddit_id not in seen:
                seen.add(post.reddit_id)
                posts.append(post)
        epoch = datetime.min.replace(tzinfo=None)
        posts.sort(key=lambda p: p.posted_at.replace(tzinfo=None) if p.posted_at else epoch, reverse=True)
        result.posts = posts[: query.max_posts]
        return result
