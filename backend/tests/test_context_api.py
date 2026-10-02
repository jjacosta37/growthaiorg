import json

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.agents.models import AgentRun
from apps.context.documents import save_document
from apps.context.models import CrawledPage
from apps.core.models import Project
from tests.fakes import message

pytestmark = pytest.mark.django_db


@pytest.fixture
def project(project):
    """The conftest project, with a site and two documents already written."""
    p = project
    p.website_url = "https://acme.example"
    p.save()
    save_document(p, "product", "# Product Information\nv1", source="ai", prompt_version="v1", model="m")
    save_document(p, "audience", "# Target Audience\nv1", source="ai", prompt_version="v1", model="m")
    return p


def test_list_docs_in_canonical_order(client, project):
    save_document(project, "compliance", "# Compliance", source="template")
    data = client.get("/api/context/docs/").json()
    assert [d["kind"] for d in data] == ["product", "audience", "compliance"]
    assert data[0]["title"] == "Product Information"


def test_edit_doc_is_human_revision(client, project):
    resp = client.patch("/api/context/docs/product/", {"content_md": "# Product Information\nedited"}, format="json")
    assert resp.status_code == 200
    assert resp.json()["source"] == "human"
    revs = client.get("/api/context/docs/product/revisions/").json()
    assert [r["source"] for r in revs] == ["human", "ai"]
    assert client.get("/api/context/docs/nope/").status_code == 404


def test_start_onboarding_enqueues_and_conflicts(client, project, django_capture_on_commit_callbacks, monkeypatch):
    calls = []
    monkeypatch.setattr("apps.context.views.onboarding_task.delay", lambda run_id: calls.append(run_id))

    with django_capture_on_commit_callbacks(execute=True):
        resp = client.post("/api/onboarding/start/", {"website_url": "https://new.example", "max_pages": 10})
    assert resp.status_code == 202
    run_id = resp.json()["id"]
    assert calls == [run_id]
    project.refresh_from_db()
    assert project.website_url == "https://new.example"

    # Any context run blocks another while it's active.
    assert client.post("/api/context/recrawl/", {}).status_code == 409
    assert client.post("/api/context/docs/product/regenerate/").status_code == 409

    AgentRun.objects.filter(pk=run_id).update(status="succeeded")
    with django_capture_on_commit_callbacks(execute=True):
        assert client.post("/api/context/recrawl/", {"overwrite_edited": True}).status_code == 202


def test_regenerate_doc_end_to_end(client, project, fake_anthropic, django_capture_on_commit_callbacks):
    CrawledPage.objects.create(project=project, url="https://acme.example/", title="Home",
                               content_text="Home " * 100, content_hash="h")
    facts = {"product_summary": "Summary.", "competitors": []}
    fake = fake_anthropic(message("# Product Information\nv2"), message(json.dumps(facts)))

    with django_capture_on_commit_callbacks(execute=True):  # Celery runs eagerly in tests
        resp = client.post("/api/context/docs/product/regenerate/")
    assert resp.status_code == 202

    run = client.get(f"/api/runs/{resp.json()['id']}/").json()
    assert run["status"] == "succeeded"
    assert client.get("/api/context/docs/product/").json()["content_md"].strip().endswith("v2")
    # The doc being regenerated is excluded from "other docs"; the audience doc is included.
    user_msg = fake.messages.calls[0]["messages"][0]["content"]
    assert "Target Audience" in user_msg and "Product Information\nv1" not in user_msg

    events = client.get(f"/api/runs/{run['id']}/events/").json()
    last = events[-1]["id"]
    assert events[-1]["message"] == "Wrote Product Information"
    assert client.get(f"/api/runs/{run['id']}/events/?after={last}").json() == []


def test_status_line_shows_active_run(client, project):
    run = AgentRun.objects.create(project=project, kind="onboarding", status="running",
                                  current_step="Writing Brand Voice")
    data = client.get("/api/status/").json()
    assert data["message"] == "Writing Brand Voice"
    assert data["active"][0]["id"] == run.id


def test_pages_endpoint(client, project):
    CrawledPage.objects.create(project=project, url="https://acme.example/a", title="A", content_text="abc",
                               content_hash="h")
    assert client.get("/api/context/pages/").json()[0]["chars"] == 3


@pytest.mark.parametrize("url", ["http://127.0.0.1:8000", "http://192.168.1.1/", "http://localhost", "http://nas.local"])
def test_start_onboarding_rejects_local_addresses(client, project, url):
    resp = client.post("/api/onboarding/start/", {"website_url": url})
    assert resp.status_code == 400
    assert "website_url" in resp.json()
    assert not AgentRun.objects.filter(project=project).exists()
