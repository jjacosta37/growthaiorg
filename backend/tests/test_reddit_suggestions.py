"""Reddit "Suggest more" (docs/prds/0004-reddit-target-suggestions.md)."""

import json

import pytest

import llm
from apps.agents.models import AgentConfig, AgentRun
from apps.agents.runs import create_run
from apps.agents.tasks import run_agent_task
from apps.inbox.models import Draft
from apps.reddit.config import RedditAgentConfig
from apps.reddit.models import RedditPost, RedditTargetSuggestion
from apps.reddit.suggestions import target_history
from apps.stats.service import build_stats
from llm.models import LLMCall
from tests.fakes import message, schema_title
from tests.reddit_helpers import configure, install_source, post, reddit_responder

pytestmark = pytest.mark.django_db

URL = "/api/agents/reddit/suggestions/"


def suggestion_reply(subreddits=(), keywords=()):
    return message(json.dumps({
        "subreddits": [{"name": n, "reason": f"why {n}"} for n in subreddits],
        "keywords": [{"term": t, "reason": f"why {t}"} for t in keywords],
    }))


def suggest(client, capture, *, expect=202):
    with capture(execute=True):
        resp = client.post(URL)
    assert resp.status_code == expect, resp.content
    return client.get(URL).json()


def values(payload, kind):
    return [r["value"] for r in payload[kind]]


def test_suggest_more_shows_new_targets_with_reasons(client, project, fake_anthropic,
                                                     django_capture_on_commit_callbacks):
    configure(project, subreddits=["projectmanagement"], keywords=["invoicing"])
    fake = fake_anthropic(suggestion_reply(["agile", "freelance"], ["late payments", "client billing"]))

    data = suggest(client, django_capture_on_commit_callbacks)

    assert values(data, "subreddits") == ["agile", "freelance"]
    assert values(data, "keywords") == ["late payments", "client billing"]
    assert data["subreddits"][0]["reason"] == "why agile"
    assert data["room"] == {"subreddits": 19, "keywords": 29}
    assert data["suggesting"] is False and data["nothing_new"] is False and data["last_error"] == ""
    # AC-12: exactly one model call, structured, with no tools.
    (call,) = fake.messages.calls
    assert schema_title(call) == "RedditTargetSuggestions" and "tools" not in call
    run = AgentRun.objects.get(kind="suggest_reddit_targets")
    assert run.status == "succeeded" and run.stats["suggested"] == 4
    assert LLMCall.objects.filter(agent_run=run).count() == 1


def test_one_suggest_run_at_a_time(client, project):
    configure(project)
    create_run(project, AgentRun.Kind.SUGGEST_REDDIT_TARGETS)
    assert client.get(URL).json()["suggesting"] is True
    assert client.post(URL).status_code == 409


def test_existing_dismissed_and_invalid_values_are_never_shown(client, project, fake_anthropic,
                                                              django_capture_on_commit_callbacks):
    configure(project, subreddits=["ProjectManagement"], keywords=["Invoicing"])
    RedditTargetSuggestion.objects.create(project=project, kind="subreddit", value="startups", key="startups",
                                          status="dismissed")
    RedditTargetSuggestion.objects.create(project=project, kind="keyword", value="cash flow", key="cash flow",
                                          status="dismissed")
    fake = fake_anthropic(suggestion_reply(
        ["r/projectmanagement", "Startups", "not a sub!", "x" * 30, "agile", "Agile"],
        ["  invoicing ", "Cash   Flow", "k" * 81, "late payments"],
    ))

    data = suggest(client, django_capture_on_commit_callbacks)

    assert values(data, "subreddits") == ["agile"]
    assert values(data, "keywords") == ["late payments"]
    assert RedditTargetSuggestion.objects.filter(status="pending").count() == 2  # invalid ones never stored
    run = AgentRun.objects.get(kind="suggest_reddit_targets")
    assert run.stats["dropped"] == {"invalid": 3, "existing": 2, "dismissed": 2, "over_cap": 0}
    # The dismissed values are shown to the model so it can steer away from them.
    user = fake.messages.calls[0]["messages"][0]["content"]
    assert "Subreddits: startups" in user and "Keywords: cash flow" in user


def test_history_reaches_the_model_including_targets_that_found_nothing(client, project, fake_anthropic,
                                                                        monkeypatch,
                                                                        django_capture_on_commit_callbacks):
    configure(project, subreddits=["projectmanagement", "smallbusiness"], keywords=["question", "invoicing"],
              relevance_threshold=70)
    install_source(monkeypatch, [post("a", "hi-yes"), post("b", "lo")])
    fake = fake_anthropic(responder=reddit_responder())
    run_agent_task(create_run(project, "reddit").id)
    assert Draft.objects.count() == 1

    cfg = RedditAgentConfig.model_validate(AgentConfig.for_project(project, "reddit").config)
    history = target_history(project, cfg)
    assert history["subreddits"] == [
        {"name": "projectmanagement", "returned": 2, "new": 2, "drafted": 1},
        {"name": "smallbusiness", "returned": 0, "new": 0, "drafted": 0},
    ]
    assert history["keywords"] == [{"term": "question", "mentions": 2, "drafted": 1},
                                   {"term": "invoicing", "mentions": 0, "drafted": 0}]

    fake.messages._responder = None
    fake.messages._responses = [suggestion_reply(["agile"])]
    suggest(client, django_capture_on_commit_callbacks)
    user = fake.messages.calls[-1]["messages"][0]["content"]
    assert "r/projectmanagement: returned 2, new 2, drafted 1" in user
    assert "r/smallbusiness: returned 0, new 0, drafted 0" in user
    assert '"invoicing": mentioned in 0 new posts, 0 drafted' in user


def test_add_appends_exactly_the_selection(client, project, fake_anthropic, django_capture_on_commit_callbacks):
    configure(project, subreddits=["projectmanagement"], keywords=["invoicing"], relevance_threshold=55,
              guidance="Be brief")
    fake_anthropic(suggestion_reply(["agile", "freelance"], ["late payments", "client billing"]))
    data = suggest(client, django_capture_on_commit_callbacks)
    pick = [data["subreddits"][1]["id"], data["keywords"][0]["id"]]

    resp = client.post(f"{URL}add/", {"ids": pick}, format="json")

    assert resp.status_code == 200 and resp.json()["added"] == 2
    config = AgentConfig.for_project(project, "reddit").config
    assert config["subreddits"] == ["projectmanagement", "freelance"]
    assert config["keywords"] == ["invoicing", "late payments"]
    assert (config["relevance_threshold"], config["guidance"]) == (55, "Be brief")
    # The unselected ones are still pending (not dismissed), the added ones are gone from the card.
    assert values(resp.json(), "subreddits") == ["agile"]
    assert values(resp.json(), "keywords") == ["client billing"]
    assert set(RedditTargetSuggestion.objects.values_list("status", flat=True)) == {"added", "pending"}


def test_add_over_the_limit_changes_nothing(client, project):
    configure(project, subreddits=[f"sub{i:02d}" for i in range(19)])
    rows = [RedditTargetSuggestion.objects.create(project=project, kind="subreddit", value=v, key=v)
            for v in ("extra1", "extra2")]
    assert client.get(URL).json()["room"]["subreddits"] == 1

    resp = client.post(f"{URL}add/", {"ids": [r.id for r in rows]}, format="json")

    assert resp.status_code == 400 and "20 subreddits" in resp.json()["detail"]
    assert len(AgentConfig.for_project(project, "reddit").config["subreddits"]) == 19
    assert set(RedditTargetSuggestion.objects.values_list("status", flat=True)) == {"pending"}


def test_dismissed_suggestions_never_return(client, project, fake_anthropic, django_capture_on_commit_callbacks):
    configure(project)
    fake_anthropic(suggestion_reply(["agile", "freelance"]), suggestion_reply(["agile", "freelance", "startups"]))
    data = suggest(client, django_capture_on_commit_callbacks)

    resp = client.post(f"{URL}{data['subreddits'][0]['id']}/dismiss/")
    assert resp.status_code == 200 and values(resp.json(), "subreddits") == ["freelance"]
    assert client.post(f"{URL}{data['subreddits'][0]['id']}/dismiss/").status_code == 404

    data = suggest(client, django_capture_on_commit_callbacks)
    # "freelance" was only left unselected, so it can come back; "agile" was dismissed.
    assert values(data, "subreddits") == ["freelance", "startups"]


def test_nothing_new(client, project, fake_anthropic, django_capture_on_commit_callbacks):
    configure(project, subreddits=["projectmanagement"])
    fake_anthropic(suggestion_reply(["projectmanagement"]))
    data = suggest(client, django_capture_on_commit_callbacks)
    assert data["nothing_new"] is True and data["subreddits"] == [] and data["keywords"] == []


def test_a_failed_suggest_keeps_the_previous_suggestions_and_config(client, project, fake_anthropic,
                                                                   django_capture_on_commit_callbacks):
    configure(project)
    before = dict(AgentConfig.for_project(project, "reddit").config)
    fake_anthropic(suggestion_reply(["agile"]), llm.LLMError("overloaded"))
    suggest(client, django_capture_on_commit_callbacks)

    data = suggest(client, django_capture_on_commit_callbacks)

    assert AgentRun.objects.filter(kind="suggest_reddit_targets").first().status == "failed"
    assert data["last_error"] and data["nothing_new"] is False
    assert values(data, "subreddits") == ["agile"]
    assert AgentConfig.for_project(project, "reddit").config == before


def test_a_new_suggest_replaces_pending_ones(client, project, fake_anthropic, django_capture_on_commit_callbacks):
    configure(project)
    fake_anthropic(suggestion_reply(["agile"]), suggestion_reply(["freelance"]))
    suggest(client, django_capture_on_commit_callbacks)
    assert values(suggest(client, django_capture_on_commit_callbacks), "subreddits") == ["freelance"]


def test_a_value_typed_into_the_config_drops_out_of_the_card(client, project):
    configure(project)
    RedditTargetSuggestion.objects.create(project=project, kind="subreddit", value="agile", key="agile")
    client.patch("/api/agents/reddit/", {"config": {"subreddits": ["projectmanagement", "r/Agile"]}},
                 format="json")
    assert client.get(URL).json()["subreddits"] == []


def test_suggest_cost_counts_under_reddit(client, project, fake_anthropic, django_capture_on_commit_callbacks):
    configure(project)
    fake_anthropic(suggestion_reply(["agile"]))
    suggest(client, django_capture_on_commit_callbacks)
    spend = build_stats(project)["spend"]
    assert set(spend["llm_by_agent"]) == {"reddit"} and spend["llm_by_agent"]["reddit"] > 0


# --- Repeat hint (AC-14) ----------------------------------------------------------------------


@pytest.mark.parametrize("enabled,window,schedule,hint", [
    (True, "week", {"kind": "every_hours", "hours": 4, "minute": 0}, {"time_window": "week", "window_hours": 168,
                                                                      "gap_hours": 4.0}),
    (True, "day", {"kind": "every_hours", "hours": 12, "minute": 0}, None),  # 24h == 2 × 12h: within bound
    (True, "day", {"kind": "every_hours", "hours": 6, "minute": 0}, {"time_window": "day", "window_hours": 24,
                                                                     "gap_hours": 6.0}),
    (False, "week", {"kind": "every_hours", "hours": 4, "minute": 0}, None),  # not scheduled
])
def test_repeat_hint(client, project, enabled, window, schedule, hint):
    cfg = configure(project, time_window=window)
    cfg.enabled, cfg.schedule = enabled, schedule
    cfg.save()
    assert client.get("/api/agents/reddit/").json()["repeat_hint"] == hint
    assert client.get("/api/agents/content/").json()["repeat_hint"] is None


def test_existing_config_is_untouched_until_suggest_more_is_used(client, project):
    cfg = configure(project, subreddits=["projectmanagement"], keywords=["invoicing"])
    before = dict(cfg.config)
    data = client.get(URL).json()
    assert data == {"suggesting": False, "last_error": "", "nothing_new": False, "subreddits": [], "keywords": [],
                    "room": {"subreddits": 19, "keywords": 29}, "limits": {"subreddits": 20, "keywords": 30}}
    assert AgentConfig.for_project(project, "reddit").config == before
    assert not RedditPost.objects.exists() and not AgentRun.objects.exists()
