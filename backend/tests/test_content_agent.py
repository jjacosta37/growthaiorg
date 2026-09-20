import json

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.agents.models import AgentConfig, AgentRun
from apps.agents.runs import create_run
from apps.agents.tasks import run_agent_task
from apps.content.models import BlogTopic
from apps.content.pipeline import finalize_post
from apps.context.models import CrawledPage
from apps.core.models import Project
from apps.core.text import is_near_duplicate, slugify
from apps.inbox.models import Draft
from llm.schemas import BlogPostDraft
from tests.fakes import message, schema_title

pytestmark = pytest.mark.django_db

PROPOSALS = [
    {"title": "Sprint Planning Guide: Strategies for Every Team", "angle": "dup of a published post",
     "target_keywords": ["sprint planning"], "pillar": "Planning", "why": "x"},
    {"title": "Running Retrospectives, Step by Step", "angle": "How a retro works",
     "target_keywords": ["sprint retrospective"], "pillar": "Team rituals", "why": "Common question"},
    {"title": "Running retrospectives: a step-by-step walkthrough", "angle": "near-dup within the batch",
     "target_keywords": ["retro meeting"], "pillar": "Team rituals", "why": "x"},
    {"title": "What a Weekly Standup Is Really For", "angle": "Standup purpose",
     "target_keywords": ["weekly standup"], "pillar": "Meetings", "why": "Common question"},
]


RETRO_BODY = "## What is a retrospective\nText.\n\n## Conclusion\nDone."


def post_json(title="Running Retrospectives, Step by Step", body=RETRO_BODY,
              meta="Learn how to run a useful retrospective."):
    return json.dumps({"title": title, "meta_description": meta, "slug": "Running Retrospectives!!",
                       "target_keywords": ["sprint retrospective", " retro meeting "], "body_md": body})


def responder(post=None, lint=None):
    def respond(params):
        title = schema_title(params)
        if title == "TopicProposals":
            return message(json.dumps({"topics": PROPOSALS}))
        if title == "BlogPostDraft":
            return message(post or post_json(title=_topic_from(params)))
        if title == "ComplianceLint":
            return message(json.dumps({"flags": lint or []}))
        raise AssertionError(title)

    return respond


def _topic_from(params):
    user = params["messages"][0]["content"]
    return user.split("Topic: ", 1)[1].split("\n", 1)[0]


@pytest.fixture
def project(project):
    p = project
    CrawledPage.objects.create(project=p, url="https://acme.example/blog/sprint-planning-guide",
                               title="Sprint Planning Guide: Strategies for Every Team",
                               content_text="x", content_hash="h")
    return p


def run_content(project, **params):
    run = create_run(project, "content", params=params)
    run_agent_task(run.id)
    run.refresh_from_db()
    return run


def test_near_duplicate_detection():
    existing = ["Sprint Planning Guide: Strategies for Every Team", "How to Estimate Project Timelines"]
    assert is_near_duplicate("Sprint planning: a guide", existing)
    assert is_near_duplicate("How to estimate project timelines accurately", existing)
    assert not is_near_duplicate("Writing better meeting notes", existing)
    assert not is_near_duplicate("The", existing)
    assert slugify("  What's a 1:1 Meeting?! ") == "what-s-a-1-1-meeting"


DISCLAIMER = "This article is for informational purposes only."


def test_finalize_post_cleans_slug_h1_and_adds_disclaimer():
    parsed = BlogPostDraft.model_validate_json(post_json(body="# Stray H1\n\n## Intro\nHello."))
    content = finalize_post(parsed, DISCLAIMER)
    assert content["slug"] == "running-retrospectives"
    assert content["keywords"] == ["sprint retrospective", "retro meeting"]
    assert content["body_md"].startswith("## Intro")
    assert content["body_md"].rstrip().endswith(f"*{DISCLAIMER}*")

    already = BlogPostDraft.model_validate_json(post_json(body=f"## Intro\nHi.\n\n*{DISCLAIMER}*"))
    assert finalize_post(already, DISCLAIMER)["body_md"].count(DISCLAIMER) == 1
    assert finalize_post(parsed, "")["body_md"].rstrip().endswith("Hello.")  # packs without a disclaimer


def test_run_proposes_dedupes_and_drafts_top_topic(project, fake_anthropic):
    BlogTopic.objects.create(project=project, title="Onboarding checklists", status="rejected")
    fake = fake_anthropic(responder=responder())

    run = run_content(project)

    assert run.status == "succeeded", run.error or run.stats
    assert run.stats == {"topics_proposed": 2, "topics_duplicate": 2, "drafted": 1}
    topics = {t.title: t.status for t in BlogTopic.objects.exclude(status="rejected")}
    assert topics == {"Running Retrospectives, Step by Step": "drafted",
                      "What a Weekly Standup Is Really For": "proposed"}

    topics_call = next(c for c in fake.messages.calls if schema_title(c) == "TopicProposals")
    user = topics_call["messages"][0]["content"]
    assert "Sprint Planning Guide" in user and "Onboarding checklists" in user  # covered + rejected

    draft = Draft.objects.get()
    assert (draft.kind, draft.agent_type, draft.blog_topic.title) == (
        "blog_post", "content", "Running Retrospectives, Step by Step")
    assert draft.current_version.content["slug"] == "running-retrospectives"
    assert draft.compliance_flags == []


def test_backlog_is_used_before_proposing(project, fake_anthropic):
    AgentConfig.objects.create(project=project, agent_type="content", config={"min_backlog": 1})
    BlogTopic.objects.create(project=project, title="Queued topic A")
    fake = fake_anthropic(responder=responder())

    run = run_content(project)

    assert "topics_proposed" not in run.stats and run.stats["drafted"] == 1
    assert not any(schema_title(c) == "TopicProposals" for c in fake.messages.calls)
    assert BlogTopic.objects.get(title="Queued topic A").status == "drafted"


def test_long_meta_description_is_flagged(project, fake_anthropic):
    fake_anthropic(responder=responder(post=post_json(meta="x" * 200)))
    BlogTopic.objects.create(project=project, title="Queued topic A")
    AgentConfig.objects.create(project=project, agent_type="content", config={"min_backlog": 0})
    run_content(project)
    flags = Draft.objects.get().compliance_flags
    assert [f["rule"] for f in flags] == ["seo"] and "200 characters" in flags[0]["explanation"]


def test_request_topic_drafts_it_now(client, project, fake_anthropic, django_capture_on_commit_callbacks):
    fake_anthropic(responder=responder())
    with django_capture_on_commit_callbacks(execute=True):
        resp = client.post("/api/agents/content/topics/", {
            "title": "Is a kanban board enough?", "angle": "Compare kanban vs. scrum",
            "target_keywords": ["kanban board"],
        }, format="json")
    assert resp.status_code == 201, resp.json()
    body = resp.json()
    assert body["topic"]["requested_by_user"] is True
    run = AgentRun.objects.get(pk=body["run"]["id"])
    assert (run.status, run.params) == ("succeeded", {"topic_id": body["topic"]["id"]})

    topic = client.get("/api/agents/content/topics/").json()["results"][0]
    assert topic["status"] == "drafted" and topic["draft_id"]
    detail = client.get(f"/api/drafts/{topic['draft_id']}/").json()
    assert detail["title"] == "Is a kanban board enough?"
    assert detail["blog_topic"]["angle"] == "Compare kanban vs. scrum"
    assert detail["copy_text"].startswith("# Is a kanban board enough?\n\n## What is a retrospective")
    assert detail["open_url"] == ""


def test_request_without_drafting_draft_later_and_reject(client, project, fake_anthropic,
                                                         django_capture_on_commit_callbacks):
    fake_anthropic(responder=responder())
    resp = client.post("/api/agents/content/topics/", {"title": "Later", "draft_now": False}, format="json")
    assert resp.status_code == 201 and resp.json()["run"] is None
    topic_id = resp.json()["topic"]["id"]
    assert client.get("/api/agents/content/topics/?status=proposed").json()["count"] == 1

    with django_capture_on_commit_callbacks(execute=True):
        assert client.post(f"/api/agents/content/topics/{topic_id}/draft/").status_code == 202
    assert BlogTopic.objects.get(pk=topic_id).status == "drafted"

    other = BlogTopic.objects.create(project=project, title="Meh")
    assert client.post(f"/api/agents/content/topics/{other.id}/reject/").json()["status"] == "rejected"
    assert client.post(f"/api/agents/content/topics/{other.id}/draft/").status_code == 409


def test_request_conflict_keeps_topic(client, project):
    AgentRun.objects.create(project=project, kind="content", status="running")
    resp = client.post("/api/agents/content/topics/", {"title": "Busy"}, format="json")
    assert resp.status_code == 409 and "saved to the backlog" in resp.json()["detail"]
    assert BlogTopic.objects.filter(title="Busy").exists()


def test_regenerate_blog_with_nudge(client, project, fake_anthropic, django_capture_on_commit_callbacks):
    fake = fake_anthropic(responder=responder())
    BlogTopic.objects.create(project=project, title="Queued topic A")
    AgentConfig.objects.create(project=project, agent_type="content", config={"min_backlog": 0})
    run_content(project)
    draft = Draft.objects.get()

    before = len(fake.messages.calls)
    with django_capture_on_commit_callbacks(execute=True):
        resp = client.post(f"/api/drafts/{draft.id}/regenerate/", {"nudge": "shorter"})
    assert resp.status_code == 202
    call = next(c for c in fake.messages.calls[before:] if schema_title(c) == "BlogPostDraft")
    user = call["messages"][0]["content"]
    assert "<previous_draft>" in user and "noticeably shorter" in user
    assert [v.source for v in draft.versions.all()] == ["ai_initial", "ai_regenerated"]
