"""Isolation between tenants.

No view defines object-level permissions: separation is entirely the `project=...` filter
fed by `current_project`. So these tests are the only thing standing between two customers'
inboxes, and they exercise the boundary from the outside, through the API.
"""

import pytest
from django.contrib.auth import get_user_model
from django_celery_beat.models import PeriodicTask

from apps.agents.models import AgentConfig, AgentRun
from apps.content.models import BlogTopic
from apps.context.documents import save_document
from apps.core.models import Project
from apps.core.selection import NoProjectSelected, current_project
from apps.inbox.models import Draft, DraftVersion

pytestmark = pytest.mark.django_db


def make_draft(project, title="secret"):
    draft = Draft.objects.create(project=project, agent_type="reddit", kind="reddit_comment")
    version = DraftVersion.objects.create(
        draft=draft, n=1, source="ai_initial", content={"body": title}
    )
    draft.current_version = version
    draft.save(update_fields=["current_version"])
    return draft


# --- The list endpoints only ever show your own rows --------------------------------------


def test_drafts_are_scoped_to_the_callers_project(client, project, other_client, other_project):
    mine = make_draft(project, "mine")
    theirs = make_draft(other_project, "theirs")

    ids = [row["id"] for row in client.get("/api/drafts/").json()["results"]]
    assert ids == [mine.id]

    other_ids = [row["id"] for row in other_client.get("/api/drafts/").json()["results"]]
    assert other_ids == [theirs.id]


def test_a_draft_you_do_not_own_is_a_404(client, project, other_project):
    theirs = make_draft(other_project)
    assert client.get(f"/api/drafts/{theirs.id}/").status_code == 404


@pytest.mark.parametrize(
    "action,payload",
    [
        ("edit", {"content": {"body": "rewritten"}}),
        ("dismiss", {"reason": "not_relevant"}),
        ("mark-posted", {}),
        ("regenerate", {}),
        ("restore", {}),
        ("read", {}),
    ],
)
def test_draft_actions_refuse_another_tenants_draft(client, project, other_project, action, payload):
    """A 404 on every write path, not just the read. Reaching the object at all would be
    enough to dismiss or overwrite someone else's draft."""
    theirs = make_draft(other_project)
    resp = client.post(f"/api/drafts/{theirs.id}/{action}/", payload, format="json")
    assert resp.status_code == 404

    theirs.refresh_from_db()
    assert theirs.status == Draft.Status.NEW
    assert theirs.current_version.content == {"body": "secret"}


def test_counts_and_stats_only_see_your_own(client, project, other_project):
    make_draft(project)
    make_draft(other_project)
    make_draft(other_project)

    assert client.get("/api/inbox/counts/").json()["total_new"] == 1
    totals = client.get("/api/stats/").json()["totals"]
    assert totals["reddit"]["generated"] == 1


def test_context_documents_are_scoped(client, project, other_project):
    save_document(project, "product", "# Mine", source="ai", prompt_version="v1", model="m")
    save_document(other_project, "product", "# Theirs", source="ai", prompt_version="v1", model="m")

    docs = client.get("/api/context/docs/").json()
    product = next(d for d in docs if d["kind"] == "product")
    assert product["content_md"].strip() == "# Mine"
    assert client.get("/api/context/docs/product/").json()["content_md"].strip() == "# Mine"


def test_runs_are_scoped(client, project, other_project):
    mine = AgentRun.objects.create(project=project, kind="reddit")
    theirs = AgentRun.objects.create(project=other_project, kind="reddit")

    assert [r["id"] for r in client.get("/api/runs/").json()["results"]] == [mine.id]
    assert client.get(f"/api/runs/{theirs.id}/").status_code == 404
    assert client.get(f"/api/runs/{theirs.id}/events/").status_code == 404


def test_topics_are_scoped(client, project, other_project):
    mine = BlogTopic.objects.create(project=project, title="Mine")
    theirs = BlogTopic.objects.create(project=other_project, title="Theirs")

    ids = [t["id"] for t in client.get("/api/agents/content/topics/").json()["results"]]
    assert ids == [mine.id]
    assert client.post(f"/api/agents/content/topics/{theirs.id}/reject/").status_code == 404

    theirs.refresh_from_db()
    assert theirs.status == "proposed"


def test_agent_config_is_per_project(client, project, other_client, other_project):
    client.patch("/api/agents/reddit/", {"config": {"subreddits": ["mine"]}}, format="json")
    other_client.patch("/api/agents/reddit/", {"config": {"subreddits": ["theirs"]}}, format="json")

    assert client.get("/api/agents/reddit/").json()["config"]["subreddits"] == ["mine"]
    assert other_client.get("/api/agents/reddit/").json()["config"]["subreddits"] == ["theirs"]

    # Each project schedules its own beat entry.
    assert PeriodicTask.objects.filter(name=f"agent:{project.pk}:reddit").exists()
    assert PeriodicTask.objects.filter(name=f"agent:{other_project.pk}:reddit").exists()


# --- Choosing a project -------------------------------------------------------------------


def test_switching_project_changes_what_you_see(client, user, project):
    second = Project.objects.create(owner=user, name="Second")
    make_draft(project, "first")
    make_draft(second, "second")

    first = Draft.objects.get(project=project)
    other = Draft.objects.get(project=second)

    assert [r["id"] for r in client.get("/api/drafts/").json()["results"]] == [first.id]

    assert client.post(f"/api/projects/{second.pk}/select/").status_code == 200
    assert [r["id"] for r in client.get("/api/drafts/").json()["results"]] == [other.id]
    assert client.get("/api/project/").json()["name"] == "Second"


def test_header_picks_the_project_without_changing_the_session(client, user, project):
    second = Project.objects.create(owner=user, name="Second")
    make_draft(project, "first")
    make_draft(second, "second")

    first = Draft.objects.get(project=project)
    other = Draft.objects.get(project=second)

    via_header = client.get("/api/drafts/", HTTP_X_PROJECT_ID=str(second.pk)).json()
    assert [r["id"] for r in via_header["results"]] == [other.id]

    # Two tabs, two projects: the header doesn't move the session's selection.
    assert [r["id"] for r in client.get("/api/drafts/").json()["results"]] == [first.id]


def test_a_project_id_you_do_not_own_falls_back_to_your_own(client, project, other_project):
    """Silently ignored rather than 403: telling the caller the id exists is itself a leak."""
    mine = make_draft(project, "mine")
    resp = client.get("/api/drafts/", HTTP_X_PROJECT_ID=str(other_project.pk))
    assert resp.status_code == 200
    assert [r["id"] for r in resp.json()["results"]] == [mine.id]


def test_selecting_someone_elses_project_is_a_404(client, other_project):
    assert client.post(f"/api/projects/{other_project.pk}/select/").status_code == 404


def test_projects_list_shows_only_your_own(client, user, project, other_project):
    rows = client.get("/api/projects/").json()["results"]
    assert [r["id"] for r in rows] == [project.pk]
    assert rows[0]["is_current"] is True


# --- Users with no project ----------------------------------------------------------------


def test_a_user_with_no_project_gets_409_rather_than_a_new_one(db):
    from rest_framework.test import APIClient

    lonely = get_user_model().objects.create_user("lonely", password="pw")
    c = APIClient()
    c.force_authenticate(lonely)

    assert c.get("/api/drafts/").status_code == 409
    assert c.get("/api/projects/").json()["results"] == []
    # The old singleton created a project on any GET. Nothing does that now.
    assert Project.objects.filter(owner=lonely).count() == 0


def test_creating_a_project_selects_it(client, user, project):
    resp = client.post("/api/projects/", {"name": "Fresh"}, format="json")
    assert resp.status_code == 201
    assert resp.json()["name"] == "Fresh"
    assert client.get("/api/project/").json()["name"] == "Fresh"
    assert Project.objects.filter(owner=user).count() == 2


def test_repeated_resolution_never_creates_a_second_project(client, user, project):
    """The old `Project.current()` raced: two callers seeing an empty table both created a
    project, orphaning whatever landed on the loser. Resolution no longer creates anything."""
    for _ in range(5):
        client.get("/api/project/")
        client.get("/api/status/")
    assert Project.objects.filter(owner=user).count() == 1


# --- Deletion ------------------------------------------------------------------------------


def test_deleting_a_project_removes_its_rows_and_beat_entries(client, user, project):
    AgentConfig.for_project(project, "reddit")
    client.patch("/api/agents/reddit/", {"enabled": True}, format="json")
    make_draft(project)
    assert PeriodicTask.objects.filter(name=f"agent:{project.pk}:reddit").exists()

    second = Project.objects.create(owner=user, name="Second")
    client.post(f"/api/projects/{second.pk}/select/")

    assert client.delete(f"/api/projects/{project.pk}/").status_code == 204
    assert not Project.objects.filter(pk=project.pk).exists()
    assert not Draft.objects.filter(project_id=project.pk).exists()
    # Beat has no FK to Project, so nothing cascades: orphans would fire forever.
    assert not PeriodicTask.objects.filter(name=f"agent:{project.pk}:reddit").exists()


def test_you_cannot_delete_someone_elses_project(client, other_project):
    assert client.delete(f"/api/projects/{other_project.pk}/").status_code == 404
    assert Project.objects.filter(pk=other_project.pk).exists()


def test_deleting_a_user_takes_their_projects(user, project):
    user.delete()
    assert not Project.objects.filter(pk=project.pk).exists()


# --- The resolver itself --------------------------------------------------------------------


def test_current_project_raises_when_the_user_has_none(rf, db):
    request = rf.get("/")
    request.user = get_user_model().objects.create_user("nobody", password="pw")
    request.session = {}
    with pytest.raises(NoProjectSelected):
        current_project(request)
