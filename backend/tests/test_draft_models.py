"""The per-agent drafting model: settings catalogue, llm override, pipelines, API."""

from decimal import Decimal

import pytest

import llm
from apps.agents.draft_models import draft_model_for
from apps.agents.models import AgentConfig, AgentRun
from apps.agents.runs import create_run
from apps.agents.tasks import run_agent_task
from apps.content.models import BlogTopic
from apps.inbox.models import Draft
from llm.models import LLMCall
from llm.pricing import compute_cost
from tests import test_content_agent, test_x_agent
from tests.conftest import write_prompt
from tests.fakes import message, schema_title
from tests.reddit_helpers import configure, install_source, post, reddit_responder

pytestmark = pytest.mark.django_db

OPUS = "claude-opus-5-5"


def set_draft_model(project, agent_type, key):
    cfg = AgentConfig.for_project(project, agent_type)
    cfg.draft_model = key
    cfg.save()
    return cfg


def models_by_schema(fake, start=0):
    return [(schema_title(c), c["model"]) for c in fake.messages.calls[start:]]


# --- Catalogue and llm override ------------------------------------------------------------


def test_catalogue_defaults(settings):
    assert settings.LLM_DRAFT_MODELS["sonnet"]["model"] == settings.LLM_MODELS["writer"]
    assert settings.LLM_DRAFT_MODELS["opus"]["model"] == OPUS
    assert settings.LLM_DRAFT_MODEL_DEFAULT == "sonnet"


def test_opus_is_priced():
    assert compute_cost(OPUS, input_tokens=1_000_000, output_tokens=100_000) == Decimal("6.000000")


def test_override_applies_to_writer_prompts_only(prompts_tmp, fake_anthropic, settings):
    write_prompt(prompts_tmp, "t.write", "v1", "model_tier: writer\nmax_tokens: 500\nschema: SmokeResult",
                 "Write.", "Go")
    write_prompt(prompts_tmp, "t.fast", "v1", "model_tier: fast\nmax_tokens: 300\nschema: SmokeResult",
                 "Score.", "Go")
    fake = fake_anthropic(*[message('{"ok": true, "echo": "x"}') for _ in range(2)])

    written = llm.complete("t.write", model=OPUS)
    llm.complete("t.fast", model=OPUS)

    assert [c["model"] for c in fake.messages.calls] == [OPUS, settings.LLM_MODELS["fast"]]
    assert written.model == OPUS
    write_call = LLMCall.objects.get(task="t.write")
    assert write_call.model == OPUS and write_call.cost_usd > 0


def test_unknown_stored_key_falls_back_to_default(project, settings):
    set_draft_model(project, "reddit", "gpt")
    assert draft_model_for(project, "reddit") == ("sonnet", settings.LLM_MODELS["writer"])
    set_draft_model(project, "reddit", "opus")
    assert draft_model_for(project, "reddit") == ("opus", OPUS)


# --- Pipelines ------------------------------------------------------------------------------


def test_reddit_drafts_and_regenerates_with_the_chosen_model(
    client, project, fake_anthropic, monkeypatch, settings, django_capture_on_commit_callbacks,
):
    configure(project)
    set_draft_model(project, "reddit", "opus")
    install_source(monkeypatch, [post("a", "hi-yes")])
    fake = fake_anthropic(responder=reddit_responder())
    run = create_run(project, "reddit", trigger=AgentRun.Trigger.MANUAL)
    run_agent_task(run.id)

    calls = models_by_schema(fake)
    assert ("RedditComment", OPUS) in calls
    assert ("RelevanceScore", settings.LLM_MODELS["fast"]) in calls  # scoring is untouched
    assert ("ComplianceLint", settings.LLM_MODELS["fast"]) in calls
    draft = Draft.objects.get()
    assert draft.current_version.model == OPUS
    assert run.events.filter(data__draft_model="opus").exists()

    set_draft_model(project, "reddit", "sonnet")  # regenerate uses the choice at the time it runs
    before = len(fake.messages.calls)
    with django_capture_on_commit_callbacks(execute=True):
        assert client.post(f"/api/drafts/{draft.id}/regenerate/", {"nudge": "shorter"}).status_code == 202
    assert ("RedditComment", settings.LLM_MODELS["writer"]) in models_by_schema(fake, before)


def test_content_post_uses_the_chosen_model_but_topics_do_not(
    client, project, fake_anthropic, settings, django_capture_on_commit_callbacks,
):
    set_draft_model(project, "content", "opus")
    fake = fake_anthropic(responder=test_content_agent.responder())
    run = create_run(project, "content")
    run_agent_task(run.id)

    calls = models_by_schema(fake)
    assert ("TopicProposals", settings.LLM_MODELS["writer"]) in calls
    assert ("BlogPostDraft", OPUS) in calls
    draft = Draft.objects.get()
    assert draft.current_version.model == OPUS
    assert BlogTopic.objects.filter(status="drafted").exists()

    before = len(fake.messages.calls)
    with django_capture_on_commit_callbacks(execute=True):
        client.post(f"/api/drafts/{draft.id}/regenerate/", {"nudge": "shorter"})
    assert ("BlogPostDraft", OPUS) in models_by_schema(fake, before)


def test_x_posts_and_revisions_use_the_chosen_model(
    client, project, fake_anthropic, settings, django_capture_on_commit_callbacks,
):
    AgentConfig.objects.create(project=project, agent_type="x", draft_model="opus",
                               config={"posts_per_run": 1, "formats": ["insight"]})
    batch = [{"format": "insight", "angle": "a", "posts": [test_x_agent.LONG]}]
    revised = {"format": "insight", "angle": "a", "posts": ["Now it fits."]}
    fake = fake_anthropic(responder=test_x_agent.responder(batch, revised=revised))
    run = create_run(project, "x")
    run_agent_task(run.id)

    calls = models_by_schema(fake)
    assert ("XPostBatch", OPUS) in calls and ("XPostItem", OPUS) in calls
    draft = Draft.objects.get()

    before = len(fake.messages.calls)
    with django_capture_on_commit_callbacks(execute=True):
        client.post(f"/api/drafts/{draft.id}/regenerate/", {"nudge": "shorter"})
    assert ("XPostItem", OPUS) in models_by_schema(fake, before)


# --- API ------------------------------------------------------------------------------------


def test_summary_shows_choice_and_options(client):
    reddit = client.get("/api/agents/reddit/").json()
    assert reddit["draft_model"] == "sonnet"
    assert reddit["draft_models"] == [{"key": "sonnet", "label": "Sonnet"}, {"key": "opus", "label": "Opus"}]


def test_patch_draft_model(client, project):
    resp = client.patch("/api/agents/content/", {"draft_model": "opus"}, format="json")
    assert resp.status_code == 200 and resp.json()["draft_model"] == "opus"
    assert AgentConfig.objects.get(project=project, agent_type="content").draft_model == "opus"
    assert client.get("/api/agents/reddit/").json()["draft_model"] == "sonnet"  # per agent


@pytest.mark.parametrize("value", [OPUS, "gpt", ""])
def test_patch_rejects_anything_but_an_available_key(client, project, value):
    resp = client.patch("/api/agents/reddit/", {"draft_model": value}, format="json")
    assert resp.status_code == 400 and "draft_model" in resp.json()
    assert AgentConfig.for_project(project, "reddit").draft_model == "sonnet"


def test_unknown_stored_key_is_reported_as_the_default(client, project):
    set_draft_model(project, "x", "retired")
    assert client.get("/api/agents/x/").json()["draft_model"] == "sonnet"

