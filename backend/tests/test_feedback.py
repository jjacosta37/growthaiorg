import json

import pytest

from apps.agents.models import AgentRun
from apps.agents.runs import create_run
from apps.agents.tasks import run_agent_task
from apps.feedback import services
from apps.feedback.models import AgentFeedback, AgentLearnings
from apps.feedback.tasks import digest_feedback_task
from apps.inbox.models import Draft
from tests.fakes import schema_title, task_system
from tests.reddit_helpers import configure, install_source, post, reddit_responder

pytestmark = pytest.mark.django_db


@pytest.fixture
def drafts(project, fake_anthropic, monkeypatch):
    configure(project, relevance_threshold=50)
    install_source(monkeypatch, [post("mid1", "mid"), post("hi1", "hi-yes")])
    fake = fake_anthropic(responder=reddit_responder())
    run = create_run(project, "reddit", trigger=AgentRun.Trigger.MANUAL)
    run_agent_task(run.id)
    return fake, {d.source_reddit_post.reddit_id: d for d in Draft.objects.all()}


def calls_for(fake, title, since=0):
    return [c for c in fake.messages.calls[since:] if schema_title(c) == title]


def test_draft_feedback_is_stored_and_digested(client, drafts, django_capture_on_commit_callbacks):
    fake, d = drafts
    url = f"/api/drafts/{d['hi1'].id}/feedback/"
    assert client.post(url, {}, format="json").status_code == 400  # neither rating nor text

    before = len(fake.messages.calls)
    with django_capture_on_commit_callbacks(execute=True):
        resp = client.post(url, {"rating": "down", "text": "Too long, and it reads like a brochure"}, format="json")

    assert resp.status_code == 200
    assert [(f["source"], f["rating"], f["text"]) for f in resp.json()["feedback"]] == [
        ("explicit", "down", "Too long, and it reads like a brochure")]
    entry = AgentFeedback.objects.get()
    assert (entry.agent_type, entry.draft_version_id) == ("reddit", d["hi1"].current_version_id)

    # The digest ran (eager Celery) and folded the entry in.
    (digest_call,) = calls_for(fake, "FeedbackDigest", before)
    user = digest_call["messages"][0]["content"]
    assert "Too long, and it reads like a brochure" in user and 'rating="down"' in user
    assert "r/projectmanagement: hi-yes: question hi1" in user
    assert "Draft excerpt: Weekly planning sessions" in user
    entry.refresh_from_db()
    assert entry.digested_at is not None
    learnings = AgentLearnings.objects.get(project=d["hi1"].project, agent_type="reddit")
    assert (learnings.writing_md, learnings.selection_md, learnings.source) == (
        "- Keep replies short.", "- Skip meme posts.", "ai")
    run = AgentRun.objects.get(kind="digest_feedback")
    assert run.status == "succeeded" and run.stats["entries"] == 1


def test_regenerate_can_remember_its_instruction(client, drafts, django_capture_on_commit_callbacks):
    _, d = drafts
    url = f"/api/drafts/{d['hi1'].id}/regenerate/"
    assert client.post(url, {"nudge": "shorter", "remember": True}, format="json").status_code == 400

    with django_capture_on_commit_callbacks(execute=True):
        client.post(url, {"nudge": "custom", "instruction": "Skip the intro"}, format="json")
    assert not AgentFeedback.objects.exists()

    with django_capture_on_commit_callbacks(execute=True):
        resp = client.post(url, {"nudge": "custom", "instruction": "Use plain words", "remember": True},
                           format="json")
    assert resp.status_code == 202
    assert "remember" not in AgentRun.objects.get(pk=resp.json()["id"]).params
    entry = AgentFeedback.objects.get()
    assert (entry.source, entry.text) == ("instruction", "Use plain words")


def test_dismissing_records_no_feedback(client, drafts):
    _, d = drafts
    client.post(f"/api/drafts/{d['hi1'].id}/dismiss/", {"reason": "other", "note": "meh"}, format="json")
    assert not AgentFeedback.objects.exists()


def test_new_drafts_see_learnings_guidance_and_undigested_feedback(project, drafts, monkeypatch):
    fake, d = drafts
    configure(project, relevance_threshold=50, guidance="Always answer in under 100 words.")
    AgentLearnings.objects.create(project=project, agent_type="reddit", writing_md="- Lead with the answer.",
                                  selection_md="- Skip posts asking for tool lists.")
    # Recorded without the digest running (no on_commit), so it's still pending.
    services.record(d["mid1"], source="explicit", rating="up", text="Loved the concrete example")
    install_source(monkeypatch, [post("hi2", "hi-yes")])

    before = len(fake.messages.calls)
    run_agent_task(create_run(project, "reddit").id)

    (score_call,) = calls_for(fake, "RelevanceScore", before)
    assert "Skip posts asking for tool lists." in task_system(score_call)
    (comment_call,) = calls_for(fake, "RedditComment", before)
    system = task_system(comment_call)
    assert "Always answer in under 100 words." in system
    assert "- Lead with the answer." in system
    assert "[liked] (r/projectmanagement: mid: question mid1) Loved the concrete example" in system
    # The learnings sit after the cache breakpoint, so the cached prefix is unchanged.
    assert "Lead with the answer" not in json.dumps(comment_call["system"][0])


def test_prompts_render_as_before_without_feedback(project, drafts):
    fake, _ = drafts
    (comment_call, _) = calls_for(fake, "RedditComment")
    system = task_system(comment_call)
    assert "<learnings>" not in system and "<instructions>" not in system and "Recent feedback" not in system
    assert "selection_preferences" not in task_system(calls_for(fake, "RelevanceScore")[0])


def test_poster_read_is_stored_with_the_draft(drafts):
    _, d = drafts
    assert d["hi1"].current_version.content == {
        "body": "Weekly planning sessions are common. Here's how to think about it...", "poster_read": "no cues"}


def test_human_edited_learnings_are_kept_and_marked(client, drafts, django_capture_on_commit_callbacks):
    fake, d = drafts
    resp = client.patch("/api/agents/reddit/learnings/", {"writing": "- Never use bullet lists."}, format="json")
    assert resp.status_code == 200 and resp.json()["source"] == "human"

    before = len(fake.messages.calls)
    with django_capture_on_commit_callbacks(execute=True):
        client.post(f"/api/drafts/{d['hi1'].id}/feedback/", {"text": "Shorter please"}, format="json")
    (digest_call,) = calls_for(fake, "FeedbackDigest", before)
    assert "- Never use bullet lists." in digest_call["messages"][0]["content"]
    assert "edited the current learnings by hand" in task_system(digest_call)


def test_digest_only_folds_pending_entries_and_reschedules(project, drafts, monkeypatch):
    fake, d = drafts
    old = services.record(d["hi1"], source="explicit", text="Old lesson")
    AgentFeedback.objects.filter(pk=old.pk).update(digested_at="2026-01-01T00:00:00Z")
    services.record(d["hi1"], source="explicit", text="New lesson")

    scheduled = []
    monkeypatch.setattr("apps.feedback.tasks.schedule_digest", lambda *a, **k: scheduled.append(a))
    respond = fake.messages._responder

    def arrive_mid_run(params):
        # A new entry lands while the digest call is in flight.
        if schema_title(params) == "FeedbackDigest":
            AgentFeedback.objects.create(project=project, agent_type="reddit", source="explicit", text="Late")
        return respond(params)

    fake.messages._responder = arrive_mid_run
    before = len(fake.messages.calls)
    digest_feedback_task(project.pk, "reddit")

    (digest_call,) = calls_for(fake, "FeedbackDigest", before)
    user = digest_call["messages"][0]["content"]
    assert "New lesson" in user and "Old lesson" not in user and "Late" not in user
    assert list(services.pending(project, "reddit").values_list("text", flat=True)) == ["Late"]
    assert scheduled == [(project.pk, "reddit")]


def test_rebuild_rereads_everything_and_clears_when_empty(client, project, drafts,
                                                          django_capture_on_commit_callbacks):
    fake, d = drafts
    a = services.record(d["hi1"], source="explicit", text="First")
    services.record(d["hi1"], source="explicit", text="Second")
    AgentFeedback.objects.update(digested_at="2026-01-01T00:00:00Z")

    before = len(fake.messages.calls)
    with django_capture_on_commit_callbacks(execute=True):
        assert client.post("/api/agents/reddit/learnings/rebuild/").status_code == 202
    user = calls_for(fake, "FeedbackDigest", before)[0]["messages"][0]["content"]
    assert user.index("First") < user.index("Second") and "(none yet)" in user

    assert client.delete(f"/api/agents/reddit/feedback/{a.pk}/").status_code == 204
    AgentFeedback.objects.all().delete()
    with django_capture_on_commit_callbacks(execute=True):
        client.post("/api/agents/reddit/learnings/rebuild/")
    learnings = AgentLearnings.objects.get(project=project, agent_type="reddit")
    assert (learnings.writing_md, learnings.selection_md) == ("", "")


def test_learnings_payload(client, drafts):
    _, d = drafts
    services.record(d["hi1"], source="explicit", rating="up")
    data = client.get("/api/agents/reddit/learnings/").json()
    assert data["pending"] == 1 and data["digesting"] is False
    assert [(e["draft"], e["draft_title"], e["rating"]) for e in data["entries"]] == [
        (d["hi1"].id, "hi-yes: question hi1", "up")]
    assert client.get("/api/agents/nope/learnings/").status_code == 404


def test_feedback_is_tenant_scoped(client, other_project, drafts):
    _, d = drafts
    theirs = AgentFeedback.objects.create(project=other_project, agent_type="reddit", source="explicit", text="x")
    AgentLearnings.objects.create(project=other_project, agent_type="reddit", writing_md="- Their secret")

    assert client.get("/api/agents/reddit/learnings/").json()["entries"] == []
    assert "Their secret" not in client.get("/api/agents/reddit/learnings/").json()["writing"]
    assert client.delete(f"/api/agents/reddit/feedback/{theirs.pk}/").status_code == 404
    assert AgentFeedback.objects.filter(pk=theirs.pk).exists()
