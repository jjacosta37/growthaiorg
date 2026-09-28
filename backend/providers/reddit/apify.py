"""RedditSource backed by the harshmaur/reddit-scraper Apify actor.

One actor run covers every subreddit: we pass Reddit search URLs (restrict_sr=1, sort=new,
OR-joined keywords) as startUrls instead of one run per subreddit, since each run has a
start fee. Verified against a live run on 2026-09-19.
"""

import logging
import math
import time
from datetime import datetime, timedelta
from decimal import Decimal
from urllib.parse import urlencode

from llm.tracing import trace_tool

from .base import RedditPostData, RedditSearch, RedditSearchResult

log = logging.getLogger(__name__)

MAX_QUERY_CHARS = 400  # Reddit rejects very long search queries; split keywords across URLs


def search_term(keyword: str) -> str:
    """Reddit search syntax for one keyword. Recall beats precision here (scoring filters later):
    - `invoicing`              → invoicing
    - `meal prep`              → (meal prep)         all words, any order
    - `"cold email"`           → "cold email"        exact phrase, only when I quote it myself
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
        run_input = self.build_input(query)
        result.queries = len(run_input["startUrls"])
        with trace_tool(
            "apify.reddit_search",
            inputs={"subreddits": query.subreddits, "keywords": query.keywords,
                    "time_window": query.time_window, "max_posts": query.max_posts},
            metadata={"actor_id": self.actor_id, "queries": result.queries},
        ) as outputs:
            self._search(query, run_input, result)
            outputs.update(apify_run_id=result.external_run_id, status=result.status,
                           items_raw=result.items_raw, posts=len(result.posts),
                           cost_usd=float(result.cost_usd), duration_ms=result.duration_ms,
                           error=result.error)
        return result

    def _search(self, query: RedditSearch, run_input: dict, result: RedditSearchResult) -> None:
        """Run the actor and fill `result`. Never raises: a failed search degrades to an
        error string so the pipeline can carry on (or stop) with the facts in hand."""
        started = time.monotonic()
        try:
            run = self.client.actor(self.actor_id).call(run_input=run_input, run_timeout=self.timeout)
        except Exception as exc:  # network/auth/actor failure: surface it on the run
            result.duration_ms = int((time.monotonic() - started) * 1000)
            log.warning("apify reddit search failed: %s", exc, exc_info=True)
            result.error = f"{type(exc).__name__}: {exc}"
            return
        if run is None:
            result.duration_ms = int((time.monotonic() - started) * 1000)
            result.status = "TIMED-OUT"
            result.error = "Apify run did not finish in time"
            return
        result.external_run_id = run.id or ""
        result.status = run.status or ""
        result.cost_usd = Decimal(str(run.usage_total_usd or 0))
        if run.status != "SUCCEEDED":
            result.error = f"Apify run {run.id} ended with status {run.status}"
        seen: set[str] = set()
        posts = []
        for item in self.client.dataset(run.default_dataset_id).iterate_items():
            result.items_raw += 1
            post = map_item(item)
            if post and post.reddit_id not in seen:
                seen.add(post.reddit_id)
                posts.append(post)
        epoch = datetime.min.replace(tzinfo=None)
        posts.sort(key=lambda p: p.posted_at.replace(tzinfo=None) if p.posted_at else epoch, reverse=True)
        result.posts = posts[: query.max_posts]
        result.duration_ms = int((time.monotonic() - started) * 1000)
