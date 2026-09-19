import json

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.agents.models import AgentRun
from apps.agents.runs import create_run
from apps.agents.tasks import run_agent_task
from apps.core.models import Project
from apps.inbox.models import Draft
from tests.reddit_helpers import configure, install_source, post, reddit_responder

pytestmark = pytest.mark.django_db


@pytest.fixture
def client():
    c = APIClient()
    c.force_authenticate(get_user_model().objects.create_user("me", password="pw"))
    return c


@pytest.fixture
def drafts(fake_anthropic, monkeypatch):
    """Two Reddit drafts (scores 90 and 60) created by a real pipeline run with fakes."""
    configure(relevance_threshold=50)
    install_source(monkeypatch, [post("mid1", "mid"), post("hi1", "hi-yes")])
    fake = fake_anthropic(responder=reddit_responder())
    run = create_run(Project.current(), "reddit", trigger=AgentRun.Trigger.MANUAL)
    run_agent_task(run.id)
    return fake, {d.source_reddit_post.reddit_id: d for d in Draft.objects.all()}


def test_list_filters_and_sorts(client, drafts):
    _, d = drafts
    by_score = client.get("/api/drafts/?sort=score").json()["results"]
    assert [r["id"] for r in by_score] == [d["hi1"].id, d["mid1"].id]
    assert by_score[0] | {"created_at": None} == {
        "id": d["hi1"].id, "channel": "reddit", "kind": "reddit_comment", "status": "new",
        "title": "hi-yes: question hi1", "score": 90, "subreddit": "projectmanagement", "unread": True, "flag_count": 0,
        "created_at": None,
    }
    assert client.get("/api/drafts/?agent=x").json()["results"] == []
    assert client.get("/api/drafts/?status=posted").json()["results"] == []


def test_detail_has_everything_to_render_and_copy(client, drafts):
    _, d = drafts
    data = client.get(f"/api/drafts/{d['hi1'].id}/").json()
    assert data["content"]["body"].startswith("Weekly planning sessions")
    assert data["copy_text"] == data["content"]["body"]
    assert data["open_url"] == "https://www.reddit.com/r/projectmanagement/comments/hi1/q/"
    assert data["source_post"]["relevance_reason"] == "because hi-yes"
    assert [v["source"] for v in data["versions"]] == ["ai_initial"]
    assert data["char_limit"] is None


def test_edit_keeps_original_ai_version(client, drafts):
    _, d = drafts
    url = f"/api/drafts/{d['hi1'].id}/edit/"
    assert client.post(url, {"content": {"body": ""}}, format="json").status_code == 400
    resp = client.post(url, {"content": {"body": "My tweaked reply"}}, format="json")
    assert resp.status_code == 200
    versions = resp.json()["versions"]
    assert [(v["n"], v["source"]) for v in versions] == [(1, "ai_initial"), (2, "human_edit")]
    assert resp.json()["content"] == {"body": "My tweaked reply"}


def test_dismiss_restore_post_read_and_counts(client, drafts):
    _, d = drafts
    counts = client.get("/api/inbox/counts/").json()
    assert counts == {"unread": 2, "ready": {"reddit": 2, "content": 0, "x": 0}, "total_new": 2, "flagged": 0}

    assert client.post(f"/api/drafts/{d['mid1'].id}/read/").status_code == 204
    assert client.get("/api/inbox/counts/").json()["unread"] == 1

    assert client.post(f"/api/drafts/{d['mid1'].id}/dismiss/", {"reason": "bogus"}).status_code == 400
    resp = client.post(f"/api/drafts/{d['mid1'].id}/dismiss/", {"reason": "already_answered", "note": "top comment"})
    assert resp.json()["status"] == "dismissed" and resp.json()["dismiss_reason"] == "already_answered"
    edit = client.post(f"/api/drafts/{d['mid1'].id}/edit/", {"content": {"body": "x"}}, format="json")
    assert edit.status_code == 409
    assert client.post(f"/api/drafts/{d['mid1'].id}/restore/").json()["status"] == "new"

    resp = client.post(f"/api/drafts/{d['hi1'].id}/mark-posted/",
                       {"posted_url": "https://www.reddit.com/r/projectmanagement/comments/hi1/q/c1/"})
    assert resp.json()["status"] == "posted" and resp.json()["posted_at"]
    assert [r["id"] for r in client.get("/api/drafts/?status=posted").json()["results"]] == [d["hi1"].id]
    assert client.get("/api/inbox/counts/").json()["ready"]["reddit"] == 1


def test_regenerate_with_nudge(client, drafts, django_capture_on_commit_callbacks):
    fake, d = drafts
    draft = d["hi1"]
    assert client.post(f"/api/drafts/{draft.id}/regenerate/", {"nudge": "custom"}).status_code == 400

    before = len(fake.messages.calls)
    with django_capture_on_commit_callbacks(execute=True):
        resp = client.post(f"/api/drafts/{draft.id}/regenerate/",
                           {"nudge": "no_mention", "instruction": "Mention the two-pizza rule"})
    assert resp.status_code == 202
    run = AgentRun.objects.get(pk=resp.json()["id"])
    assert (run.kind, run.status) == ("regenerate_draft", "succeeded")

    comment_call = next(c for c in fake.messages.calls[before:]
                        if "RedditComment" in json.dumps(c.get("output_config", {})))
    user = comment_call["messages"][0]["content"]
    assert "<previous_draft>" in user and "Don't mention Acme at all" in user and "two-pizza rule" in user

    versions = client.get(f"/api/drafts/{draft.id}/").json()["versions"]
    assert [(v["source"], v["nudge"]) for v in versions] == [("ai_initial", ""), ("ai_regenerated", "no_mention")]


def test_regenerate_conflict_and_state(client, drafts):
    _, d = drafts
    draft = d["hi1"]
    AgentRun.objects.create(project=draft.project, kind="regenerate_draft", status="running",
                            params={"draft_id": draft.id})
    assert client.post(f"/api/drafts/{draft.id}/regenerate/", {"nudge": "shorter"}).status_code == 409
    client.post(f"/api/drafts/{d['mid1'].id}/dismiss/", {"reason": "other"})
    assert client.post(f"/api/drafts/{d['mid1'].id}/regenerate/", {"nudge": "shorter"}).status_code == 409
