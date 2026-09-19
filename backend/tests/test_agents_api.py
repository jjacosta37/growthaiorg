import json

import pytest
from django.contrib.auth import get_user_model
from django_celery_beat.models import PeriodicTask
from rest_framework.test import APIClient

from apps.core.models import Project
from tests.reddit_helpers import configure, install_source, post, reddit_responder

pytestmark = pytest.mark.django_db


@pytest.fixture
def client():
    c = APIClient()
    c.force_authenticate(get_user_model().objects.create_user("me", password="pw"))
    return c


def test_list_agents_with_defaults(client):
    agents = client.get("/api/agents/").json()
    reddit = next(a for a in agents if a["agent_type"] == "reddit")
    assert reddit["enabled"] is False and reddit["cron"] == "0 */4 * * *"
    assert reddit["config"]["relevance_threshold"] == 70 and reddit["config"]["subreddits"] == []
    assert reddit["next_run_at"] is None and reddit["last_run"] is None and reddit["ready"] == 0


def test_patch_config_validates_merges_and_schedules(client):
    configure()
    resp = client.patch("/api/agents/reddit/", {"config": {"relevance_threshold": 150}}, format="json")
    assert resp.status_code == 400
    assert client.patch("/api/agents/reddit/", {"cron": "every hour"}, format="json").status_code == 400

    resp = client.patch("/api/agents/reddit/", {
        "enabled": True, "cron": "15 */3 * * *",
        "config": {"relevance_threshold": 60, "subreddits": ["r/productivity", "productivity", " startups "]},
    }, format="json")
    assert resp.status_code == 200, resp.json()
    data = resp.json()
    assert data["config"]["subreddits"] == ["productivity", "startups"]  # normalized + deduped
    assert data["config"]["keywords"] == ["invoicing"]  # untouched keys kept
    assert data["next_run_at"] is not None

    task = PeriodicTask.objects.get(name=f"agent:{Project.current().pk}:reddit")
    assert task.enabled and task.task == "apps.agents.tasks.run_scheduled_agent"
    assert (task.crontab.minute, task.crontab.hour) == ("15", "*/3")
    assert json.loads(task.args) == [Project.current().pk, "reddit"]

    client.patch("/api/agents/reddit/", {"enabled": False}, format="json")
    assert not PeriodicTask.objects.get(name=task.name).enabled


def test_unknown_agent_404(client):
    assert client.get("/api/agents/tiktok/").status_code == 404
    assert client.post("/api/agents/tiktok/run-now/").status_code == 404


def test_run_now_conflict_and_skipped_list(client, fake_anthropic, monkeypatch, django_capture_on_commit_callbacks):
    configure()
    install_source(monkeypatch, [post("a", "hi-yes"), post("b", "hi-no"), post("c", "lo")])
    fake_anthropic(responder=reddit_responder())

    with django_capture_on_commit_callbacks(execute=True):
        resp = client.post("/api/agents/reddit/run-now/")
    assert resp.status_code == 202
    run_id = resp.json()["id"]
    assert client.get(f"/api/runs/{run_id}/").json()["status"] == "succeeded"

    runs = client.get("/api/agents/reddit/runs/").json()["results"]
    assert [r["id"] for r in runs] == [run_id]

    skipped = client.get("/api/agents/reddit/skipped/").json()["results"]
    assert [(s["title"][:5], s["relevance_score"], s["reply_worthwhile"]) for s in skipped] == [
        ("hi-no", 85, False), ("lo: q", 10, False)]
    assert len(client.get("/api/agents/reddit/skipped/?min_score=50").json()["results"]) == 1
    assert client.get(f"/api/agents/reddit/skipped/?run={run_id}").json()["count"] == 2

    summary = client.get("/api/agents/reddit/").json()
    assert summary["last_run"]["id"] == run_id and summary["ready"] == 1

    from apps.agents.models import AgentRun

    AgentRun.objects.create(project=Project.current(), kind="reddit", status="running")
    assert client.post("/api/agents/reddit/run-now/").status_code == 409



def test_custom_validator_errors_return_400_not_500(client):
    resp = client.patch("/api/agents/x/", {"config": {"formats": ["dance"]}}, format="json")
    assert resp.status_code == 400 and "Unknown formats" in str(resp.json())


def test_configs_created_anywhere_use_the_agents_default_schedule():
    from apps.agents.models import AgentConfig

    project = Project.current()
    assert AgentConfig.for_project(project, "reddit").cron == "0 */4 * * *"  # e.g. created by onboarding
    assert AgentConfig.for_project(project, "content").cron == "0 9 * * 1"
    assert AgentConfig.for_project(project, "x").cron == "0 14 * * 1-5"
