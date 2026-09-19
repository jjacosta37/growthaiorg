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
    run = create_run(project or Project.current(), "reddit", trigger=trigger)
    run_agent_task(run.id)
    run.refresh_from_db()
    return run


@pytest.fixture
def project():
    return Project.current()


def test_manual_run_scores_sync_and_drafts_above_threshold(project, fake_anthropic, monkeypatch):
    configure(project)
    source = install_source(monkeypatch, [post("a", "hi-yes"), post("b", "hi-no"), post("c", "mid"),
                                          post("d", "lo"), post("a", "hi-yes")])
    fake = fake_anthropic(responder=reddit_responder())

    run = run_now(project)

    assert run.status == "succeeded", run.error or run.stats
    assert source.queries[0].subreddits == ["Bogleheads"] and source.queries[0].keywords == ["rebalancing"]
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
