import json

import pytest

from apps.agents.models import AgentRun, ExternalUsage
from apps.agents.runs import create_run
from apps.agents.tasks import run_agent_task, run_scheduled_agent
from apps.core.models import Project
from apps.inbox.models import Draft
from apps.reddit import tasks as reddit_tasks
from apps.reddit.models import RedditPost
from llm.models import LLMBatch, LLMCall
from llm.prompts import load_prompt
from providers.reddit import RedditSearchResult
from tests.fakes import message
from tests.reddit_helpers import configure, install_source, post, reddit_responder

pytestmark = pytest.mark.django_db


def run_now(project=None, trigger=AgentRun.Trigger.MANUAL):
    run = create_run(project, "reddit", trigger=trigger)
    run_agent_task(run.id)
    run.refresh_from_db()
    return run


def test_manual_run_scores_sync_and_drafts_above_threshold(project, fake_anthropic, monkeypatch):
    configure(project)
    source = install_source(monkeypatch, [post("a", "hi-yes"), post("b", "hi-no"), post("c", "mid"),
                                          post("d", "lo"), post("a", "hi-yes")])
    fake = fake_anthropic(responder=reddit_responder())

    run = run_now(project)

    assert run.status == "succeeded", run.error or run.stats
    assert source.queries[0].subreddits == ["projectmanagement"] and source.queries[0].keywords == ["invoicing"]
    assert RedditPost.objects.count() == 4  # duplicate "a" in the same fetch collapsed
    assert run.stats == {"fetched": 5, "new_posts": 4, "duplicates": 1, "scored": 4, "above_threshold": 1,
                         "threshold": 70, "drafted": 1}

    draft = Draft.objects.get()
    assert draft.source_reddit_post.reddit_id == "a" and draft.kind == "reddit_comment"
    v = draft.current_version
    assert (v.n, v.source, v.prompt_name, v.prompt_version, v.model) == (
        1, "ai_initial", "reddit.comment", load_prompt("reddit.comment").version, "claude-sonnet-5")
    assert draft.compliance_flags == []

    # hi-no (85 but not worthwhile), mid (60 < 70) and lo stay in the skipped list with their scores
    skipped = RedditPost.objects.filter(drafts__isnull=True).order_by("-relevance_score")
    assert [(p.reddit_id, p.relevance_score) for p in skipped] == [("b", 85), ("c", 60), ("d", 10)]

    # The comment prompt got the post and the reason; context docs sit in the cached prefix.
    comment_call = next(c for c in fake.messages.calls if "RedditComment" in json.dumps(c.get("output_config", {})))
    assert "question a" in comment_call["messages"][0]["content"]
    assert "because hi-yes" in comment_call["messages"][0]["content"]
    assert comment_call["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert not ExternalUsage.objects.exists()  # fake source isn't billed


def test_second_run_dedupes_against_database(project, fake_anthropic, monkeypatch):
    configure(project)
    install_source(monkeypatch, [post("a", "hi-yes")])
    fake_anthropic(responder=reddit_responder())
    run_now(project)

    run = run_now(project)

    assert run.stats["new_posts"] == 0 and run.stats["duplicates"] == 1
    assert "No new posts" in run.events.last().message
    assert Draft.objects.count() == 1


def test_product_mention_without_disclosure_is_flagged(project, fake_anthropic, monkeypatch):
    configure(project)
    install_source(monkeypatch, [post("a", "hi-yes")])
    fake_anthropic(responder=reddit_responder(comment_body="Try Acme, it tracks this for you."))
    run_now(project)
    flags = Draft.objects.get().compliance_flags
    assert [f["rule"] for f in flags] == ["missing_disclosure"]
    assert "(Disclosure: I'm the founder of Acme.)" in flags[0]["explanation"]


def test_llm_lint_flags_are_stored(project, fake_anthropic, monkeypatch):
    configure(project)
    install_source(monkeypatch, [post("a", "hi-yes")])
    lint = [{"rule": "returns_claim", "excerpt": "beat the market", "explanation": "implies returns"}]
    fake_anthropic(responder=reddit_responder(lint_flags=lint))
    run_now(project)
    assert Draft.objects.get().compliance_flags == lint


def test_scheduled_run_uses_batch_then_finishes(project, fake_anthropic, monkeypatch):
    configure(project, relevance_threshold=50)
    install_source(monkeypatch, [post("a", "hi-yes"), post("c", "mid"), post("d", "lo")])
    fake = fake_anthropic(responder=reddit_responder())
    responder = reddit_responder()
    fake.messages.batches.answer = lambda cid, params: responder(params)
    fake.messages.batches.ended = False
    polls = []
    monkeypatch.setattr(reddit_tasks.poll_scoring_batch, "apply_async", lambda args, countdown: polls.append(args))

    run = run_now(project, trigger=AgentRun.Trigger.SCHEDULED)

    assert run.status == "waiting_batch"
    assert "in a batch" in run.current_step
    b = LLMBatch.objects.get()
    assert b.request_count == 3 and polls == [(run.pk,)]
    assert not LLMCall.objects.filter(task="reddit.score").exists()  # nothing scored synchronously

    reddit_tasks.poll_scoring_batch(run.pk)  # batch not finished yet → reschedule
    run.refresh_from_db()
    assert run.status == "waiting_batch" and len(polls) == 2

    fake.messages.batches.ended = True
    reddit_tasks.poll_scoring_batch(run.pk)
    run.refresh_from_db()

    assert run.status == "succeeded", run.error
    assert run.stats["drafted"] == 2  # hi-yes (90) and mid (60) clear the threshold of 50
    assert LLMCall.objects.filter(task="reddit.score", is_batch=True).count() == 3
    assert RedditPost.objects.filter(score_status="scored").count() == 3


def test_expired_batch_fails_run(project, fake_anthropic, monkeypatch, settings):
    configure(project)
    install_source(monkeypatch, [post("a", "hi-yes")])
    fake = fake_anthropic(responder=reddit_responder())
    fake.messages.batches.ended = False
    monkeypatch.setattr(reddit_tasks.poll_scoring_batch, "apply_async", lambda args, countdown: None)
    run = run_now(project, trigger=AgentRun.Trigger.SCHEDULED)

    settings.LLM_BATCH_MAX_AGE_HOURS = 0
    reddit_tasks.poll_scoring_batch(run.pk)
    run.refresh_from_db()
    assert run.status == "failed" and "didn't finish" in run.error


def test_scoring_failure_is_partial(project, fake_anthropic, monkeypatch):
    configure(project)
    install_source(monkeypatch, [post("a", "hi-yes"), post("d", "lo")])
    ok = reddit_responder()

    def respond(params):
        if "lo:" in params["messages"][0]["content"]:
            return message("garbage")
        return ok(params)

    fake_anthropic(responder=respond)
    run = run_now(project)
    assert run.status == "partial"
    failed = RedditPost.objects.get(reddit_id="d")
    assert failed.score_status == "failed" and "schema" in failed.score_error
    assert Draft.objects.count() == 1


def test_empty_config_and_search_errors_fail(project, fake_anthropic, monkeypatch):
    fake_anthropic(responder=reddit_responder())
    configure(project, subreddits=[])
    run = run_now(project)
    assert run.status == "failed" and "Add at least one subreddit" in run.error

    configure(project)

    class Broken:
        name = "apify"

        def search(self, q):
            return RedditSearchResult(provider="apify", resource_id="harshmaur/reddit-scraper", error="HTTP 401")

    monkeypatch.setattr("apps.reddit.pipeline.get_source", lambda: Broken())
    run = run_now(project)
    assert run.status == "failed" and "HTTP 401" in run.error
    assert ExternalUsage.objects.get().error == "HTTP 401"  # failed Apify runs are still recorded


def test_scheduled_entry_point_respects_enabled_and_conflicts(project, fake_anthropic, monkeypatch):
    cfg = configure(project)
    install_source(monkeypatch, [post("a", "hi-yes")])
    fake_anthropic(responder=reddit_responder())
    monkeypatch.setattr(reddit_tasks.poll_scoring_batch, "apply_async", lambda args, countdown: None)

    run_scheduled_agent(project.pk, "reddit")
    assert not AgentRun.objects.exists()  # disabled

    cfg.enabled = True
    cfg.save()
    run_scheduled_agent(project.pk, "reddit")
    run = AgentRun.objects.get()
    assert (run.trigger, run.status) == ("scheduled", "waiting_batch")

    run_scheduled_agent(project.pk, "reddit")  # previous run still waiting on its batch → skipped
    assert AgentRun.objects.count() == 1


# --- Run trail ---------------------------------------------------------------------------
# The events are what explains a run after the fact, so their `data` is asserted like any
# other output. Messages stay one line; the detail rides in `data`.


def events_of(run):
    from apps.agents.models import RunEvent

    return list(RunEvent.objects.filter(run=run))


def event_with(run, key):
    return next(e for e in events_of(run) if key in e.data)


def test_the_fetch_event_names_every_configured_subreddit(project, fake_anthropic, monkeypatch):
    """A subreddit that returned nothing is the fact this step used to hide, so it is
    reported as an explicit zero rather than by being absent."""
    configure(project, subreddits=["projectmanagement", "smallbusiness"])
    install_source(monkeypatch, [post("a", "hi-yes"), post("b", "mid")])  # both in projectmanagement
    fake_anthropic(responder=reddit_responder())

    run = run_now(project)

    data = event_with(run, "by_subreddit").data
    assert data["by_subreddit"] == {"projectmanagement": 2, "smallbusiness": 0}
    assert (data["fetched"], data["new_posts"], data["duplicates"]) == (2, 2, 0)


def test_the_scoring_event_carries_the_distribution_and_the_top_posts(project, fake_anthropic, monkeypatch):
    configure(project)
    install_source(monkeypatch, [post("a", "hi-yes"), post("b", "mid"), post("c", "lo")])
    fake_anthropic(responder=reddit_responder())

    run = run_now(project)

    data = event_with(run, "distribution").data
    assert (data["scored"], data["failed"]) == (3, 0)
    assert data["distribution"] == {"0-24": 1, "25-49": 0, "50-74": 1, "75-100": 1}
    top = data["top"]
    assert [p["reddit_id"] for p in top] == ["a", "b", "c"]  # highest score first
    assert top[0]["score"] == 90 and top[0]["reply_worthwhile"] is True
    assert "body of" not in json.dumps(data).lower()  # identifiers and scores, never content


def test_the_scoring_event_is_reported_on_the_batch_path_too(project, fake_anthropic, monkeypatch):
    """The batch path scores in a different place; it must not be second-class in the trail."""
    configure(project, batch_scheduled_scoring=True)
    install_source(monkeypatch, [post("a", "hi-yes"), post("b", "lo")])
    responder = reddit_responder()
    fake = fake_anthropic(responder=responder)
    fake.messages.batches.answer = lambda cid, params: responder(params)
    monkeypatch.setattr(reddit_tasks.poll_scoring_batch, "apply_async", lambda args, countdown: None)

    run = run_now(project, trigger=AgentRun.Trigger.SCHEDULED)
    assert run.status == "waiting_batch"
    reddit_tasks.poll_scoring_batch(run.pk)
    run.refresh_from_db()

    assert run.status == "succeeded", run.error
    assert event_with(run, "distribution").data["scored"] == 2


def test_the_search_is_costed_and_reported_as_one_event(project, fake_anthropic, monkeypatch):
    """The adapter's facts (run id, duration, raw item count) reach the trail, not just the DB."""
    from decimal import Decimal

    configure(project)
    source = install_source(monkeypatch, [post("a", "hi-yes")])
    source.name = "apify"

    def search(query):
        return RedditSearchResult(posts=[post("a", "hi-yes")], provider="apify", resource_id="acme/scraper",
                                  external_run_id="apify_1", cost_usd=Decimal("0.02"), status="SUCCEEDED",
                                  duration_ms=3000, items_raw=7, queries=2)

    source.search = search
    fake_anthropic(responder=reddit_responder())

    run = run_now(project)

    usage = ExternalUsage.objects.get()
    assert (usage.status, usage.duration_ms, usage.external_run_id) == ("SUCCEEDED", 3000, "apify_1")
    data = event_with(run, "items_raw").data
    assert (data["items_raw"], data["queries"], data["items"]) == (7, 2, 1)
    assert data["cost_usd"] == pytest.approx(0.02)
