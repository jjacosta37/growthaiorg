from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from providers.reddit import ApifyRedditSource, RedditSearch
from providers.reddit.apify import keyword_queries, map_item, search_urls

# Field names and shape copied from a live harshmaur/reddit-scraper run (2026-09-19); values changed.
LIVE_ITEM = {
    "id": "t3_1wknhpm", "parsedId": "1wknhpm", "title": "How do you track deadlines across small teams?",
    "body": "We're a team of five and keep missing deadlines...", "authorName": "x_user",
    "contentUrl": "https://www.reddit.com/r/smallbusiness/comments/1wknhpm/how_do_you/",
    "postUrl": "https://www.reddit.com/r/smallbusiness/comments/1wknhpm/how_do_you/",
    "parsedCommunityName": "smallbusiness", "communityName": "r/smallbusiness", "flair": "Question",
    "upVotes": 2, "commentsCount": 4, "dataType": "post", "createdAt": "2026-09-19T14:19:54.000Z",
}


def test_map_live_item():
    p = map_item(LIVE_ITEM)
    assert (p.reddit_id, p.subreddit, p.upvotes, p.num_comments, p.flair) == (
        "1wknhpm", "smallbusiness", 2, 4, "Question")
    assert p.posted_at == datetime(2026, 9, 19, 14, 19, 54, tzinfo=UTC)
    assert p.url.endswith("/1wknhpm/how_do_you/")


def test_map_skips_non_posts_and_tolerates_missing_fields():
    assert map_item({**LIVE_ITEM, "dataType": "comment"}) is None
    p = map_item({"dataType": "post", "id": "t3_abc", "communityName": "r/startups", "title": "t",
                  "contentUrl": "https://www.reddit.com/r/startups/comments/abc/t/"})
    assert (p.reddit_id, p.subreddit, p.upvotes, p.posted_at) == ("abc", "startups", 0, None)


def test_keyword_queries_favor_recall():
    assert keyword_queries(["invoicing", " team   deadlines ", '"cold email"', "", '""', "a (b)"]) == [
        'invoicing OR (team deadlines) OR "cold email" OR (a b)'
    ]
    many = [f"keyword number {i}" for i in range(40)]
    queries = keyword_queries(many)
    assert len(queries) > 1 and all(len(q) <= 400 for q in queries)
    assert sum(q.count("(") for q in queries) == 40  # nothing dropped


def test_search_urls_one_per_subreddit_and_query():
    urls = search_urls(RedditSearch(subreddits=["r/startups", "productivity/"], keywords=["invoicing"],
                                    time_window="week"))
    assert [urlparse(u).path for u in urls] == ["/r/startups/search/", "/r/productivity/search/"]
    qs = parse_qs(urlparse(urls[0]).query)
    assert qs == {"q": ["invoicing"], "restrict_sr": ["1"], "sort": ["new"], "t": ["week"]}


class FakeApify:
    def __init__(self, items, status="SUCCEEDED", error=None):
        self.items, self.status, self.error, self.inputs = items, status, error, []

    def actor(self, actor_id):
        fake = self

        class A:
            def call(self, run_input, run_timeout):
                fake.inputs.append(run_input)
                if fake.error:
                    raise fake.error
                return SimpleNamespace(id="run9", status=fake.status, usage_total_usd=0.02, default_dataset_id="d")

        return A()

    def dataset(self, _):
        items = self.items

        class D:
            def iterate_items(self):
                return iter(items)

        return D()


def item(pid, created):
    return {**LIVE_ITEM, "id": f"t3_{pid}", "parsedId": pid, "createdAt": created}


def test_search_dedupes_sorts_caps_and_costs():
    client = FakeApify([
        item("a", "2026-09-19T10:00:00Z"), item("b", "2026-09-19T12:00:00Z"), item("a", "2026-09-19T10:00:00Z"),
        {**item("c", "2026-09-19T11:00:00Z"), "dataType": "comment"}, item("d", None),
    ])
    src = ApifyRedditSource("tok", client=client)
    r = src.search(RedditSearch(subreddits=["startups", "productivity"], keywords=["x"], max_posts=2))
    assert [p.reddit_id for p in r.posts] == ["b", "a"]  # newest first, deduped, capped; undated last
    assert (r.cost_usd, r.external_run_id, r.error) == (Decimal("0.02"), "run9", "")
    run_input = client.inputs[0]
    assert len(run_input["startUrls"]) == 2 and run_input["crawlCommentsPerPost"] is False
    assert run_input["maxPostsCount"] >= 1


def test_search_failures():
    r = ApifyRedditSource("tok", client=FakeApify([], error=RuntimeError("boom"))).search(
        RedditSearch(subreddits=["a"], keywords=["b"]))
    assert r.posts == [] and "boom" in r.error
    r = ApifyRedditSource("tok", client=FakeApify([item("a", None)], status="FAILED")).search(
        RedditSearch(subreddits=["a"], keywords=["b"]))
    assert "FAILED" in r.error and len(r.posts) == 1
    empty = ApifyRedditSource("tok", client=FakeApify([])).search(RedditSearch(subreddits=[], keywords=["b"]))
    assert empty.posts == []
