import json
from urllib.parse import parse_qs, urlparse

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.agents.models import AgentConfig
from apps.agents.runs import create_run
from apps.agents.tasks import run_agent_task
from apps.core.models import Project
from apps.inbox.models import Draft
from apps.xagent.config import FORMATS, XAgentConfig
from apps.xagent.length import x_length
from apps.xagent.pipeline import plan_formats
from tests.fakes import message, schema_title

pytestmark = pytest.mark.django_db

LONG = "a" * 350


def test_x_length_weighting():
    assert x_length("hello") == 5
    assert x_length("see https://example.com/a/very/long/path?with=query for more") == len("see  for more") + 23
    assert x_length("日本語") == 6  # CJK counts double
    assert x_length("ship it 🚀") == len("ship it ") + 2
    assert x_length("family 👨‍👩‍👧") == len("family ") + 2  # a ZWJ sequence is one emoji


def test_plan_formats_rotates_least_recently_used():
    cfg = XAgentConfig(formats=["insight", "question", "thread"], posts_per_run=2)
    assert plan_formats(cfg, []) == ["insight", "question"]
    recent = [{"format": "insight"}, {"format": "question"}]  # newest first; thread never used
    assert plan_formats(cfg, recent) == ["thread", "question"]
    assert plan_formats(XAgentConfig(formats=["insight"], posts_per_run=3), []) == ["insight"] * 3


def test_config_validation():
    with pytest.raises(ValueError):
        XAgentConfig(formats=["dance"])
    with pytest.raises(ValueError):
        XAgentConfig(formats=[])
    assert set(XAgentConfig().formats) == set(FORMATS)


def responder(batch, revised=None, lint=None):
    def respond(params):
        title = schema_title(params)
        if title == "XPostBatch":
            return message(json.dumps({"items": batch}))
        if title == "XPostItem":
            return message(json.dumps(revised))
        if title == "ComplianceLint":
            return message(json.dumps({"flags": lint or []}))
        raise AssertionError(title)

    return respond


@pytest.fixture
def project():
    p = Project.current()
    p.name = "Acme"
    p.save()
    AgentConfig.objects.create(project=p, agent_type="x", config={"posts_per_run": 3,
                                                                   "formats": ["insight", "thread", "question"]})
    return p


def run_x(project):
    run = create_run(project, "x")
    run_agent_task(run.id)
    run.refresh_from_db()
    return run


def test_run_drafts_posts_and_threads(project, fake_anthropic):
    batch = [
        {"format": "insight", "angle": "small teams",
         "posts": ["Small teams ship faster when one person owns each deadline."]},
        {"format": "thread", "angle": "retros",
         "posts": ["How we run a 20-minute retro:", "1. What went well", "  ", "3. One change"]},
        {"format": "question", "angle": "tooling",
         "posts": ["What's the one planning ritual your team would never drop?"]},
    ]
    fake = fake_anthropic(responder=responder(batch))

    run = run_x(project)

    assert run.status == "succeeded", run.error or run.stats
    assert run.stats == {"planned": 3, "drafted": 3, "duplicates": 0, "revised": 0, "over_limit": 0}
    drafts = {d.current_version.content["format"]: d for d in Draft.objects.all()}
    assert drafts["insight"].kind == "x_post" and drafts["thread"].kind == "x_thread"
    assert drafts["thread"].current_version.content["posts"] == ["How we run a 20-minute retro:", "1. What went well",
                                                                  "3. One change"]  # blanks dropped
    call = next(c for c in fake.messages.calls if schema_title(c) == "XPostBatch")
    user = call["messages"][0]["content"]
    assert "1. insight:" in user and "2. thread:" in user and "3. question:" in user


def test_over_limit_is_revised_then_flagged_if_still_long(project, fake_anthropic):
    batch = [{"format": "insight", "angle": "a", "posts": [LONG]},
             {"format": "thread", "angle": "b", "posts": ["Short hook", LONG]}]
    revised = {"format": "insight", "angle": "a", "posts": ["Now it fits."]}
    calls = []

    def respond(params):
        title = schema_title(params)
        if title == "XPostItem":
            calls.append(params)
            # First revision fits; the second one is still too long.
            return message(json.dumps(revised if len(calls) == 1 else {**revised, "posts": ["Hook", LONG]}))
        return responder(batch)(params)

    fake_anthropic(responder=respond)
    run = run_x(project)

    assert run.stats["revised"] == 2 and run.stats["over_limit"] == 1 and run.stats["drafted"] == 2
    revise_msg = calls[0]["messages"][0]["content"]
    assert "is 350" in revise_msg and "280-character limit" in revise_msg
    fixed, flagged = Draft.objects.order_by("id")
    assert fixed.current_version.content["posts"] == ["Now it fits."] and fixed.compliance_flags == []
    assert fixed.current_version.prompt_name == "x.revise"
    assert [f["rule"] for f in flagged.compliance_flags] == ["length"]
    assert "Post 2 is 350 characters" in flagged.compliance_flags[0]["explanation"]


def test_repeats_of_recent_posts_are_skipped(project, fake_anthropic):
    fake_anthropic(responder=responder([{"format": "insight", "angle": "a",
                                         "posts": ["Small teams ship faster when one person owns each deadline."]}]))
    run_x(project)
    fake_anthropic(responder=responder([
        {"format": "insight", "angle": "a",
         "posts": ["Small teams ship faster when a single person owns each deadline!"]},
        {"format": "question", "angle": "b", "posts": ["Which meeting would you cancel first?"]},
    ]))
    run = run_x(project)
    assert run.stats["duplicates"] == 1 and run.stats["drafted"] == 1


def test_recent_drafts_are_sent_and_formats_rotate(project, fake_anthropic):
    fake_anthropic(responder=responder([{"format": "insight", "angle": "a", "posts": ["First idea about deadlines."]}]))
    cfg = AgentConfig.objects.get(project=project, agent_type="x")
    cfg.config = {**cfg.config, "posts_per_run": 1}
    cfg.save()
    run_x(project)

    fake = fake_anthropic(responder=responder([{"format": "thread", "angle": "b", "posts": ["Another", "idea"]}]))
    run_x(project)
    user = next(c for c in fake.messages.calls if schema_title(c) == "XPostBatch")["messages"][0]["content"]
    assert "[insight] First idea about deadlines." in user
    assert "1. thread:" in user  # insight was used last time


@pytest.fixture
def client():
    c = APIClient()
    c.force_authenticate(get_user_model().objects.create_user("me", password="pw"))
    return c


def test_detail_edit_and_regenerate(client, project, fake_anthropic, django_capture_on_commit_callbacks):
    batch = [{"format": "thread", "angle": "retros", "posts": ["Retros in 20 minutes & why", "Step one"]}]
    fake = fake_anthropic(responder=responder(batch, revised={"format": "thread", "angle": "retros",
                                                              "posts": ["Shorter retro thread", "Done"]}))
    run_x(project)
    draft = Draft.objects.get()

    data = client.get(f"/api/drafts/{draft.id}/").json()
    assert data["char_limit"] == 280 and data["kind"] == "x_thread"
    assert data["title"] == "Retros in 20 minutes & why"
    qs = parse_qs(urlparse(data["open_url"]).query)
    assert data["open_url"].startswith("https://x.com/intent/post?") and qs["text"] == ["Retros in 20 minutes & why"]
    assert data["copy_text"] == "Retros in 20 minutes & why\n\nStep one"

    # Partial edit keeps format/angle.
    resp = client.post(f"/api/drafts/{draft.id}/edit/", {"content": {"posts": ["Edited hook", "Step one"]}},
                       format="json")
    assert resp.json()["content"] == {"posts": ["Edited hook", "Step one"], "format": "thread", "angle": "retros"}

    before = len(fake.messages.calls)
    with django_capture_on_commit_callbacks(execute=True):
        assert client.post(f"/api/drafts/{draft.id}/regenerate/", {"nudge": "shorter"}).status_code == 202
    revise_call = next(c for c in fake.messages.calls[before:] if schema_title(c) == "XPostItem")
    assert "noticeably shorter" in revise_call["messages"][0]["content"]
    assert "Edited hook" in revise_call["messages"][0]["content"]  # revises the current (edited) version
    versions = client.get(f"/api/drafts/{draft.id}/").json()["versions"]
    assert [v["source"] for v in versions] == ["ai_initial", "human_edit", "ai_regenerated"]
    assert versions[-1]["content"]["posts"] == ["Shorter retro thread", "Done"]


def test_char_limit_is_configurable(client, project):
    resp = client.patch("/api/agents/x/", {"config": {"char_limit": 4000}}, format="json")
    assert resp.status_code == 200 and resp.json()["config"]["char_limit"] == 4000
    assert client.patch("/api/agents/x/", {"config": {"formats": ["dance"]}}, format="json").status_code == 400
