import json

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.agents.models import AgentConfig, AgentRun
from apps.agents.runs import create_run
from apps.agents.tasks import run_agent_task
from apps.content.models import BlogTopic
from apps.content.pipeline import finalize_post
from apps.content.topics import is_near_duplicate, slugify
from apps.context.models import CrawledPage
from apps.core.models import Project
from apps.inbox.models import Draft
from llm.schemas import BlogPostDraft
from tests.fakes import message, schema_title

pytestmark = pytest.mark.django_db

PROPOSALS = [
    {"title": "Portfolio Rebalancing Guide: Strategies for Every Investor", "angle": "dup of a published post",
     "target_keywords": ["rebalancing"], "pillar": "Investing", "why": "x"},
    {"title": "Roth Conversion Ladders, Step by Step", "angle": "How a ladder works",
     "target_keywords": ["roth conversion ladder"], "pillar": "Taxes", "why": "Common question"},
    {"title": "Roth conversion ladder: a step-by-step walkthrough", "angle": "near-dup within the batch",
     "target_keywords": ["roth ladder"], "pillar": "Taxes", "why": "x"},
    {"title": "What an Employer 401(k) Match Is Really Worth", "angle": "Match math",
     "target_keywords": ["401k match"], "pillar": "Retirement", "why": "Free money"},
]


def post_json(title="Roth Conversion Ladders, Step by Step", body="## What is a ladder\nText.\n\n## Conclusion\nDone.",
              meta="Learn how a Roth conversion ladder works."):
    return json.dumps({"title": title, "meta_description": meta, "slug": "Roth Conversion Ladders!!",
                       "target_keywords": ["roth conversion ladder", " backdoor roth "], "body_md": body})


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
def project():
    p = Project.current()
    CrawledPage.objects.create(project=p, url="https://ow.example/blog/portfolio-rebalancing-guide",
                               title="Portfolio Rebalancing Guide: Strategies for Every Investor",
                               content_text="x", content_hash="h")
    return p


def run_content(project, **params):
    run = create_run(project, "content", params=params)
    run_agent_task(run.id)
    run.refresh_from_db()
    return run


def test_near_duplicate_detection():
    existing = ["Portfolio Rebalancing Guide: Strategies for Every Investor", "How to Calculate Diversification"]
    assert is_near_duplicate("Portfolio rebalancing: a guide", existing)
    assert is_near_duplicate("How to calculate portfolio diversification", existing)
    assert not is_near_duplicate("Roth conversion ladders explained", existing)
    assert not is_near_duplicate("The", existing)
    assert slugify("  What's a 401(k) Match?! ") == "what-s-a-401-k-match"


DISCLAIMER = "This article is for informational purposes only."


def test_finalize_post_cleans_slug_h1_and_adds_disclaimer():
    parsed = BlogPostDraft.model_validate_json(post_json(body="# Stray H1\n\n## Intro\nHello."))
    content = finalize_post(parsed, DISCLAIMER)
    assert content["slug"] == "roth-conversion-ladders"
    assert content["keywords"] == ["roth conversion ladder", "backdoor roth"]
    assert content["body_md"].startswith("## Intro")
    assert content["body_md"].rstrip().endswith(f"*{DISCLAIMER}*")

    already = BlogPostDraft.model_validate_json(post_json(body=f"## Intro\nHi.\n\n*{DISCLAIMER}*"))
    assert finalize_post(already, DISCLAIMER)["body_md"].count(DISCLAIMER) == 1
    assert finalize_post(parsed, "")["body_md"].rstrip().endswith("Hello.")  # packs without a disclaimer


def test_run_proposes_dedupes_and_drafts_top_topic(project, fake_anthropic):
    BlogTopic.objects.create(project=project, title="Emergency fund sizing", status="rejected")
    fake = fake_anthropic(responder=responder())

    run = run_content(project)

    assert run.status == "succeeded", run.error or run.stats
    assert run.stats == {"topics_proposed": 2, "topics_duplicate": 2, "drafted": 1}
    topics = {t.title: t.status for t in BlogTopic.objects.exclude(status="rejected")}
    assert topics == {"Roth Conversion Ladders, Step by Step": "drafted",
                      "What an Employer 401(k) Match Is Really Worth": "proposed"}

    topics_call = next(c for c in fake.messages.calls if schema_title(c) == "TopicProposals")
    user = topics_call["messages"][0]["content"]
    assert "Portfolio Rebalancing Guide" in user and "Emergency fund sizing" in user  # covered + rejected

    draft = Draft.objects.get()
    assert (draft.kind, draft.agent_type, draft.blog_topic.title) == (
        "blog_post", "content", "Roth Conversion Ladders, Step by Step")
    assert draft.current_version.content["slug"] == "roth-conversion-ladders"
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


@pytest.fixture
def client():
    c = APIClient()
    c.force_authenticate(get_user_model().objects.create_user("me", password="pw"))
    return c


def test_request_topic_drafts_it_now(client, project, fake_anthropic, django_capture_on_commit_callbacks):
    fake_anthropic(responder=responder())
    with django_capture_on_commit_callbacks(execute=True):
        resp = client.post("/api/agents/content/topics/", {
            "title": "Is a robo-advisor enough?", "angle": "Compare robo vs. human",
            "target_keywords": ["robo advisor"],
        }, format="json")
    assert resp.status_code == 201, resp.json()
    body = resp.json()
    assert body["topic"]["requested_by_user"] is True
    run = AgentRun.objects.get(pk=body["run"]["id"])
    assert (run.status, run.params) == ("succeeded", {"topic_id": body["topic"]["id"]})

    topic = client.get("/api/agents/content/topics/").json()["results"][0]
    assert topic["status"] == "drafted" and topic["draft_id"]
    detail = client.get(f"/api/drafts/{topic['draft_id']}/").json()
    assert detail["title"] == "Is a robo-advisor enough?"
    assert detail["blog_topic"]["angle"] == "Compare robo vs. human"
    assert detail["copy_text"].startswith("# Is a robo-advisor enough?\n\n## What is a ladder")
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
