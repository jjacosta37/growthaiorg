"""Evidence-backed topics (PRD 0001): Reddit evidence, keyword search data and the opportunity ranking."""

import json
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.agents.models import AgentConfig, AgentRun, ExternalUsage, RunEvent
from apps.agents.runs import create_run
from apps.agents.tasks import run_agent_task
from apps.content.config import OpportunityWeights
from apps.content.models import BlogTopic
from apps.content.opportunity import opportunity, rank_topics, with_evidence_count
from apps.content.pipeline import keyword_placement
from apps.content.research import relevant_posts
from apps.inbox.models import Draft
from apps.reddit import tasks as reddit_tasks
from apps.reddit.models import RedditPost
from providers.keywords import FakeKeywordSource, KeywordLookupResult, KeywordMetrics
from providers.reddit import FakeRedditSource
from tests.fakes import message, schema_title
from tests.reddit_helpers import configure, install_source, post, reddit_responder

pytestmark = pytest.mark.django_db

POST_ID = re.compile(r'<post id="(\d+)"')


def topic_spec(title, keywords, evidence=()):
    return {"title": title, "keywords": keywords, "evidence": list(evidence)}


def content_responder(make_topics, post_json=None):
    """Answers the content prompts. `make_topics(post_ids)` builds the proposals from the ids of
    the posts the topics prompt was given; Reddit scoring falls through to the Reddit responder."""
    reddit = reddit_responder()

    def respond(params):
        title = schema_title(params)
        if title == "TopicProposals":
            ids = [int(i) for i in POST_ID.findall(params["messages"][0]["content"])]
            topics = [{"title": t["title"], "angle": "a", "target_keywords": t["keywords"], "pillar": "p",
                       "why": "w", "evidence_post_ids": t["evidence"]} for t in make_topics(ids)]
            return message(json.dumps({"topics": topics}))
        if title == "BlogPostDraft":
            return message(post_json or json.dumps({
                "title": "A post", "meta_description": "m", "slug": "a-post", "target_keywords": ["x"],
                "body_md": "## Section\nText."}))
        return reddit(params)

    return respond


def install_keywords(monkeypatch, source):
    monkeypatch.setattr("apps.content.keywords.get_keyword_source", lambda: source)
    return source


def stored_post(project, reddit_id, score, *, days_old=1, status=RedditPost.ScoreStatus.SCORED, **extra):
    posted = timezone.now() - timedelta(days=days_old)
    extra.setdefault("reply_worthwhile", True)
    return RedditPost.objects.create(
        project=project, reddit_id=reddit_id, subreddit="projectmanagement", title=f"Question {reddit_id}",
        body="body", url=f"https://www.reddit.com/r/projectmanagement/comments/{reddit_id}/", posted_at=posted,
        score_status=status, relevance_score=score, **extra,
    )


def run_content(project, **params):
    run = create_run(project, "content", params=params)
    run_agent_task(run.id)
    run.refresh_from_db()
    return run


def content_config(project, **config):
    cfg = AgentConfig.for_project(project, "content")
    cfg.config = {"min_backlog": 3, "drafts_per_run": 1, **config}
    cfg.save()
    return cfg


# --- AC-1, AC-3: which posts are evidence ---------------------------------------------------


def test_relevant_posts_are_recent_above_threshold_and_unused(project, other_project):
    configure(project)
    fresh = stored_post(project, "fresh", 80)
    dismissed_reply = stored_post(project, "dismissed", 75, reply_worthwhile=False)
    stored_post(project, "below", 60)
    stored_post(project, "old", 95, days_old=40)
    stored_post(project, "unscored", None, status=RedditPost.ScoreStatus.PENDING)
    used = stored_post(project, "used", 90)
    BlogTopic.objects.create(project=project, title="Rejected", status="rejected").evidence_posts.add(used)
    stored_post(other_project, "theirs", 99)

    assert relevant_posts(project, 70) == [fresh, dismissed_reply]


# --- AC-2, AC-18: grouping and the run trail -----------------------------------------------


def test_posts_are_grouped_into_topics_with_their_evidence(project, other_project, fake_anthropic, monkeypatch):
    configure(project)
    content_config(project)
    p1, p2, p3 = (stored_post(project, f"p{i}", 90) for i in (1, 2, 3))
    theirs = stored_post(other_project, "theirs", 99)
    install_keywords(monkeypatch, FakeKeywordSource())
    fake_anthropic(responder=content_responder(lambda ids: [
        topic_spec("Grouped question", ["grouped question"], [p1.pk, p2.pk]),
        # p1 again, an id that wasn't sent, and another project's post: only p3 sticks
        topic_spec("Second question", ["second question"], [p3.pk, p1.pk, 999_999, theirs.pk]),
        topic_spec("Strategy topic", ["strategy topic"]),
    ]))

    run = run_content(project)

    evidence = {t.title: {p.reddit_id for p in t.evidence_posts.all()} for t in BlogTopic.objects.all()}
    assert evidence == {"Grouped question": {"p1", "p2"}, "Second question": {"p3"}, "Strategy topic": set()}
    assert {k: run.stats[k] for k in ("posts_considered", "posts_grouped", "topics_with_evidence")} == {
        "posts_considered": 3, "posts_grouped": 3, "topics_with_evidence": 2}
    grouped = RunEvent.objects.get(run=run, message__startswith="Model proposed")
    assert grouped.data["groups"][0] == {"title": "Grouped question", "posts": 2}
    assert not theirs.blog_topics.exists()
    assert {p1, p2, p3} == set(RedditPost.objects.filter(blog_topics__isnull=False, project=project))


# --- AC-5, AC-7, AC-8: search data, dropping and "Low volume" ------------------------------


def test_zero_volume_topics_are_dropped_unless_reddit_backed(project, fake_anthropic, monkeypatch):
    configure(project)
    content_config(project, drafts_per_run=0)
    stored_post(project, "p1", 90)
    install_keywords(monkeypatch, FakeKeywordSource({"popular phrase": KeywordMetrics(1200, 35),
                                                     "niche phrase": KeywordMetrics(20, 10)}))
    fake_anthropic(responder=content_responder(lambda ids: [
        topic_spec("Community question", ["nobody searches this"], ids),
        topic_spec("Unwanted topic", ["nobody searches that either"]),
        topic_spec("Popular topic", ["niche phrase", "popular phrase"]),
    ]))

    run = run_content(project)

    topics = {t.title: t for t in BlogTopic.objects.all()}
    assert set(topics) == {"Community question", "Popular topic"}
    assert run.stats["topics_no_demand"] == 1
    community, popular = topics["Community question"], topics["Popular topic"]
    assert (community.search_volume, community.low_volume, community.search_status) == (0, True, "ready")
    assert (popular.primary_keyword, popular.search_volume, popular.keyword_difficulty) == ("popular phrase", 1200, 35)
    assert popular.low_volume is False and len(popular.keyword_metrics) == 2


def test_requested_topic_gets_search_data_before_drafting(client, project, fake_anthropic, monkeypatch,
                                                         django_capture_on_commit_callbacks):
    source = install_keywords(monkeypatch, FakeKeywordSource({"kanban board": KeywordMetrics(5000, 40)}))
    fake = fake_anthropic(responder=content_responder(lambda ids: []))
    with django_capture_on_commit_callbacks(execute=True):
        resp = client.post("/api/agents/content/topics/", {"title": "Is a kanban board enough?",
                                                           "target_keywords": ["Kanban  Board"]}, format="json")
    body = client.get("/api/agents/content/topics/").json()["results"][0]
    assert resp.status_code == 201
    assert (body["primary_keyword"], body["search_volume"], body["search_status"]) == ("kanban board", 5000, "ready")
    assert source.queries[0].keywords == ["kanban board"]
    post_call = next(c for c in fake.messages.calls if schema_title(c) == "BlogPostDraft")
    assert "Primary keyword: kanban board" in post_call["messages"][0]["content"]


def test_requested_topic_without_keywords_is_looked_up_by_title(client, project, monkeypatch):
    source = install_keywords(monkeypatch, FakeKeywordSource({}))
    client.post("/api/agents/content/topics/", {"title": "Later, maybe", "draft_now": False}, format="json")
    content_config(project, min_backlog=0, drafts_per_run=0)

    run_content(project)

    topic = BlogTopic.objects.get()
    assert source.queries[0].keywords == ["later, maybe"]
    assert (topic.search_status, topic.search_volume, topic.low_volume) == ("ready", 0, True)  # requested: kept


def test_requested_topic_keywords_are_validated(client):
    resp = client.post("/api/agents/content/topics/", {"title": "x", "target_keywords": "not a list",
                                                       "draft_now": False}, format="json")
    assert resp.status_code == 400
    resp = client.post("/api/agents/content/topics/", {"title": "x", "target_keywords": ["k"] * 6,
                                                       "draft_now": False}, format="json")
    assert resp.status_code == 400


# --- AC-6: the search market ----------------------------------------------------------------


def test_lookups_use_the_projects_market_and_record_it(client, project, fake_anthropic, monkeypatch):
    content_config(project, search_country="GB", search_language="en", drafts_per_run=0)
    source = install_keywords(monkeypatch, FakeKeywordSource())
    fake_anthropic(responder=content_responder(lambda ids: [topic_spec("A topic", ["a phrase"])]))

    run_content(project)
    assert (source.queries[0].country, source.queries[0].language) == ("GB", "en")
    assert BlogTopic.objects.get().search_market == "GB/en"

    resp = client.patch("/api/agents/content/", {"config": {"search_country": "DE", "search_language": "de"}},
                        format="json")
    assert resp.status_code == 200
    assert BlogTopic.objects.get().search_market == "GB/en"  # later lookups only
    assert client.patch("/api/agents/content/", {"config": {"search_country": "XX"}},
                        format="json").status_code == 400
    assert client.patch("/api/agents/content/", {"config": {"search_language": "klingon"}},
                        format="json").status_code == 400


# --- AC-11, AC-13: budget and failure ---------------------------------------------------------


def test_lookup_budget_defers_topics_to_a_later_run(project, fake_anthropic, monkeypatch, settings):
    settings.KEYWORD_LOOKUPS_PER_RUN = 3
    content_config(project, drafts_per_run=0)
    source = install_keywords(monkeypatch, FakeKeywordSource())
    fake_anthropic(responder=content_responder(lambda ids: [
        topic_spec("First topic", ["one a", "one b"]),
        topic_spec("Second topic", ["two a", "two b"]),
        topic_spec("Third topic", ["three a"]),
    ]))

    run = run_content(project)

    status = dict(BlogTopic.objects.values_list("title", "search_status"))
    assert status == {"First topic": "ready", "Second topic": "pending", "Third topic": "ready"}
    assert source.queries[0].keywords == ["one a", "one b", "three a"]
    assert (run.stats["keywords_looked_up"], run.stats["topics_lookup_deferred"]) == (3, 1)

    run_content(project)  # backlog is full now: no proposals, only the pending lookup
    assert BlogTopic.objects.get(title="Second topic").search_status == "ready"
    assert source.queries[1].keywords == ["two a", "two b"]


def test_failed_lookup_keeps_topics_pending_and_still_drafts(project, fake_anthropic, monkeypatch):
    content_config(project)
    install_keywords(monkeypatch, FakeKeywordSource(error="actor exploded"))
    fake_anthropic(responder=content_responder(lambda ids: [topic_spec("Unlooked topic", ["some phrase"])]))

    run = run_content(project)

    assert run.status == "succeeded"
    topic = BlogTopic.objects.get()
    assert (topic.status, topic.search_status) == ("drafted", "pending")  # kept: no evidence, but no data either
    assert run.stats["topics_lookup_failed"] == 1 and run.stats["drafted"] == 1
    assert any("Keyword lookup failed" in w for w in run.stats["warnings"])


def test_missing_token_degrades_to_pending(project, fake_anthropic, settings):
    settings.KEYWORD_SOURCE = "apify"
    content_config(project, drafts_per_run=0)
    fake_anthropic(responder=content_responder(lambda ids: [topic_spec("A topic", ["a phrase"])]))

    run = run_content(project)

    assert run.status == "succeeded" and BlogTopic.objects.get().search_status == "pending"
    assert any("Keyword lookup unavailable" in w for w in run.stats["warnings"])


# --- AC-12: spend --------------------------------------------------------------------------


class ApifyLikeSource(FakeKeywordSource):
    """A fake that reports itself as Apify, so the spend path runs without the network."""

    def lookup(self, query):
        result = super().lookup(query)
        return KeywordLookupResult(metrics=result.metrics, without_data=result.without_data, provider="apify",
                                   resource_id="keywordlab/keyword-search-volume", external_run_id="r1",
                                   cost_usd=Decimal("0.044"), status="SUCCEEDED", duration_ms=900,
                                   items_raw=len(result.metrics))


def test_lookup_spend_is_recorded_and_shown_in_stats(client, project, fake_anthropic, monkeypatch):
    content_config(project, drafts_per_run=0)
    install_keywords(monkeypatch, ApifyLikeSource())
    fake_anthropic(responder=content_responder(lambda ids: [topic_spec("A topic", ["a phrase"])]))

    run = run_content(project)

    usage = ExternalUsage.objects.get(agent_run=run)
    assert (usage.purpose, usage.cost_usd, usage.external_run_id) == ("keyword_lookup", Decimal("0.044"), "r1")
    assert client.get("/api/stats/").json()["spend"]["apify_by_purpose"]["keyword_lookup"] == 0.044


# --- AC-9, AC-9a, AC-9b, AC-10: ranking and sorting -------------------------------------------


def ranked_topic(project, title, volume=None, difficulty=None, evidence=0, requested=False, minutes_ago=0):
    t = BlogTopic.objects.create(project=project, title=title, requested_by_user=requested,
                                 search_status="ready" if volume is not None else "pending",
                                 search_volume=volume, keyword_difficulty=difficulty)
    BlogTopic.objects.filter(pk=t.pk).update(created_at=timezone.now() - timedelta(minutes=minutes_ago))
    for i in range(evidence):
        t.evidence_posts.add(stored_post(project, f"{title[:8]}{i}", 90))
    return t


def titles(project, weights=None):
    return [t.title for t in rank_topics(with_evidence_count(BlogTopic.objects.filter(project=project)),
                                         weights or OpportunityWeights())]


@pytest.mark.parametrize("better,worse", [
    # Differ in one signal only, including far past any "big enough" point.
    ({"volume": 400_000, "difficulty": 50, "evidence": 1}, {"volume": 200_000, "difficulty": 50, "evidence": 1}),
    ({"volume": 500, "difficulty": 20, "evidence": 1}, {"volume": 500, "difficulty": 60, "evidence": 1}),
    ({"volume": 500, "difficulty": 50, "evidence": 12}, {"volume": 500, "difficulty": 50, "evidence": 11}),
])
def test_each_signal_ranks_in_its_direction(project, better, worse):
    ranked_topic(project, "Worse", worse["volume"], worse["difficulty"], worse["evidence"], minutes_ago=5)
    ranked_topic(project, "Better", better["volume"], better["difficulty"], better["evidence"])
    assert titles(project) == ["Better", "Worse"]


def test_requested_first_then_scored_then_pending(project):
    ranked_topic(project, "Pending old", minutes_ago=30)
    ranked_topic(project, "Strong", 9000, 10, 5)
    ranked_topic(project, "Asked later", requested=True, minutes_ago=1)
    ranked_topic(project, "Asked first", requested=True, minutes_ago=10)
    ranked_topic(project, "Weak", 10, 90)
    assert titles(project) == ["Asked first", "Asked later", "Strong", "Weak", "Pending old"]


def test_off_weights_leave_a_signal_out(project):
    ranked_topic(project, "Searched", 50_000, 50, 0, minutes_ago=5)
    ranked_topic(project, "Discussed", 10, 50, 9)
    assert titles(project, OpportunityWeights(volume="high", ease="off", reddit="off")) == ["Searched", "Discussed"]
    assert titles(project, OpportunityWeights(volume="off", ease="off", reddit="high")) == ["Discussed", "Searched"]
    all_off = OpportunityWeights(volume="off", ease="off", reddit="off")
    assert titles(project, all_off) == ["Searched", "Discussed"]  # oldest first
    assert opportunity(BlogTopic.objects.get(title="Searched"), all_off) == 0.0


def test_changing_weights_reorders_the_backlog_and_the_next_draft(client, project, fake_anthropic):
    ranked_topic(project, "Searched", 50_000, 50, 0)
    ranked_topic(project, "Discussed", 10, 50, 9)
    url = "/api/agents/content/topics/?status=proposed"

    client.patch("/api/agents/content/", {"config": {"weights": {"volume": "off", "ease": "off", "reddit": "high"},
                                                     "min_backlog": 0}}, format="json")
    assert [t["title"] for t in client.get(url).json()["results"]] == ["Discussed", "Searched"]
    client.patch("/api/agents/content/", {"config": {"weights": {"volume": "high", "ease": "low", "reddit": "off"}}},
                 format="json")
    assert [t["title"] for t in client.get(url).json()["results"]] == ["Searched", "Discussed"]

    fake_anthropic(responder=content_responder(lambda ids: []))
    run_content(project)
    assert Draft.objects.get().blog_topic.title == "Searched"
    assert client.patch("/api/agents/content/", {"config": {"weights": {"volume": "max"}}},
                        format="json").status_code == 400


def test_backlog_sorts(client, project):
    ranked_topic(project, "Big hard", 9000, 80, 1, minutes_ago=3)
    ranked_topic(project, "Small easy", 100, 10, 4, minutes_ago=2)
    ranked_topic(project, "Pending", minutes_ago=1)

    def order(sort):
        return [t["title"] for t in client.get(f"/api/agents/content/topics/?sort={sort}").json()["results"]]

    assert order("volume") == ["Big hard", "Small easy", "Pending"]
    assert order("difficulty") == ["Small easy", "Big hard", "Pending"]
    assert order("evidence") == ["Small easy", "Big hard", "Pending"]
    assert order("newest") == ["Pending", "Small easy", "Big hard"]
    assert client.get("/api/agents/content/topics/?sort=bogus").status_code == 400


# --- AC-4, AC-16: evidence in the API, and tenancy ----------------------------------------------


def test_topic_shows_its_evidence_links(client, project):
    topic = ranked_topic(project, "Asked a lot", 300, 20, 2)
    RedditPost.objects.filter(blog_topics=topic).update(url="javascript:alert(1)")  # defence in depth
    body = client.get("/api/agents/content/topics/").json()["results"][0]
    assert body["evidence_count"] == 2
    assert {e["url"] for e in body["evidence"]} == {""}
    assert {e["subreddit"] for e in body["evidence"]} == {"projectmanagement"}


def test_unsafe_post_urls_are_never_stored(project, fake_anthropic, monkeypatch):
    configure(project)
    bad = post("x", "hi-yes")
    bad.url = "javascript:alert(document.cookie)"
    install_source(monkeypatch, [bad])
    fake_anthropic(responder=reddit_responder())
    run = create_run(project, "reddit")
    run_agent_task(run.id)
    assert RedditPost.objects.get().url == "https://www.reddit.com/r/projectmanagement/comments/x/"


# --- AC-14, AC-14a, AC-14b: topic research on Reddit --------------------------------------------


def test_research_fetch_when_there_is_no_evidence(project, fake_anthropic, monkeypatch):
    configure(project)  # the Reddit Agent itself is not enabled
    content_config(project, drafts_per_run=0)
    source = install_source(monkeypatch, [post("a", "hi-yes"), post("b", "lo")])
    install_keywords(monkeypatch, FakeKeywordSource())
    fake_anthropic(responder=content_responder(lambda ids: [topic_spec("From research", ["research q"], ids)]))

    run = run_content(project)

    assert len(source.queries) == 1
    posts = {p.reddit_id: p for p in RedditPost.objects.all()}
    assert {p.found_by for p in posts.values()} == {"topic_research"}
    assert {p.score_status for p in posts.values()} == {"scored"}
    assert not Draft.objects.filter(agent_type="reddit").exists()  # no replies from a content run
    assert [p.reddit_id for p in BlogTopic.objects.get().evidence_posts.all()] == ["a"]
    assert run.stats["posts_considered"] == 1
    assert RunEvent.objects.filter(run=run, message__startswith="Researching topics on Reddit").exists()


def test_research_posts_get_replies_on_the_next_reddit_run(project, fake_anthropic, monkeypatch):
    configure(project)
    content_config(project, drafts_per_run=0)
    install_source(monkeypatch, [post("a", "hi-yes"), post("b", "hi-no"), post("c", "lo")])
    install_keywords(monkeypatch, FakeKeywordSource())
    fake_anthropic(responder=content_responder(lambda ids: [topic_spec("From research", ["research q"], ids)]))
    run_content(project)

    install_source(monkeypatch, [])  # the next Reddit run finds nothing new
    reddit_run = create_run(project, "reddit")
    run_agent_task(reddit_run.id)
    reddit_run.refresh_from_db()

    assert reddit_run.stats["carried_over"] == 3
    assert list(Draft.objects.filter(agent_type="reddit").values_list("source_reddit_post__reddit_id", flat=True)) \
        == ["a"]
    assert set(RedditPost.objects.values_list("handoff_run", flat=True)) == {reddit_run.pk}

    again = create_run(project, "reddit")
    run_agent_task(again.id)
    again.refresh_from_db()
    assert "carried_over" not in again.stats and Draft.objects.filter(agent_type="reddit").count() == 1


def test_research_posts_are_carried_over_on_the_batch_path(project, fake_anthropic, monkeypatch):
    configure(project, relevance_threshold=50)
    stored_post(project, "found", 90, found_by="topic_research")
    install_source(monkeypatch, [post("n", "lo")])
    fake = fake_anthropic(responder=reddit_responder())
    responder = reddit_responder()
    fake.messages.batches.answer = lambda cid, params: responder(params)
    monkeypatch.setattr(reddit_tasks.poll_scoring_batch, "apply_async", lambda args, countdown: None)
    run = create_run(project, "reddit", trigger=AgentRun.Trigger.SCHEDULED)
    run_agent_task(run.id)
    run.refresh_from_db()
    assert run.status == "waiting_batch" and "carried_over" not in run.stats

    reddit_tasks.poll_scoring_batch(run.pk)
    run.refresh_from_db()
    assert run.stats["carried_over"] == 1
    assert Draft.objects.get().source_reddit_post.reddit_id == "found"


def test_no_research_without_reddit_config(project, fake_anthropic, monkeypatch):
    content_config(project, drafts_per_run=0)
    source = install_source(monkeypatch, [post("a", "hi-yes")])
    install_keywords(monkeypatch, FakeKeywordSource())
    fake_anthropic(responder=content_responder(lambda ids: [topic_spec("Context topic", ["context q"])]))

    run = run_content(project)

    assert source.queries == [] and run.stats["no_evidence_reason"] == "reddit_not_configured"
    assert BlogTopic.objects.get().search_status == "ready"


def test_research_that_finds_nothing_relevant_says_so(project, fake_anthropic, monkeypatch):
    configure(project)
    content_config(project, drafts_per_run=0)
    install_source(monkeypatch, [post("c", "lo")])
    install_keywords(monkeypatch, FakeKeywordSource())
    fake_anthropic(responder=content_responder(lambda ids: [topic_spec("Context topic", ["context q"])]))

    run = run_content(project)

    assert run.stats["no_evidence_reason"] == "nothing_relevant" and BlogTopic.objects.count() == 1


def test_failed_research_fetch_warns_and_carries_on(project, fake_anthropic, monkeypatch):
    configure(project)
    content_config(project, drafts_per_run=0)

    class Broken(FakeRedditSource):
        def search(self, query):
            result = super().search(query)
            result.posts, result.error = [], "search down"
            return result

    monkeypatch.setattr("apps.reddit.pipeline.get_source", lambda: Broken([]))
    install_keywords(monkeypatch, FakeKeywordSource())
    fake_anthropic(responder=content_responder(lambda ids: [topic_spec("Context topic", ["context q"])]))

    run = run_content(project)

    assert run.status == "succeeded" and run.stats["no_evidence_reason"] == "research_failed"
    assert any("Topic research on Reddit failed" in w for w in run.stats["warnings"])
    assert BlogTopic.objects.count() == 1


# --- AC-17: keyword placement ----------------------------------------------------------------


def test_keyword_placement_check():
    good = {"title": "Sprint Retrospective Basics", "body_md": "A sprint retrospective is…\n\n## Running a sprint "
                                                               "retrospective\nText."}
    assert keyword_placement(good, "sprint retrospective") == []
    bad = {"title": "Retros", "body_md": "## Intro\nNothing here.\n\n## More\nStill nothing."}
    assert keyword_placement(bad, "Sprint  Retrospective") == ["title", "first paragraph", "H2"]


# --- Reddit config bounds (spend) -----------------------------------------------------------------


def test_reddit_config_bounds_subreddits_and_keywords(client):
    def patch(config):
        return client.patch("/api/agents/reddit/", {"config": config}, format="json")

    assert patch({"subreddits": [f"sub{i}" for i in range(21)]}).status_code == 400
    assert patch({"keywords": [f"kw{i}" for i in range(31)]}).status_code == 400
    assert patch({"keywords": ["x" * 81]}).status_code == 400
    assert patch({"subreddits": ["../etc"]}).status_code == 400
    assert patch({"subreddits": ["r/Valid_Name"]}).json()["config"]["subreddits"] == ["Valid_Name"]


def test_posted_at_fallback_uses_fetch_time(project):
    configure(project)
    p = stored_post(project, "nodate", 90)
    RedditPost.objects.filter(pk=p.pk).update(posted_at=None)
    assert [x.reddit_id for x in relevant_posts(project, 70)] == ["nodate"]
    RedditPost.objects.filter(pk=p.pk).update(fetched_at=datetime.now(UTC) - timedelta(days=31))
    assert relevant_posts(project, 70) == []
