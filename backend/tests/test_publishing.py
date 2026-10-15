"""Blog drafts as GitHub pull requests (docs/prds/0002-github-blog-prs.md), against FakeGitHost.

Each test names the AC it checks. Tenant isolation is in test_tenancy.py.
"""

import logging
from datetime import date
from urllib.parse import parse_qs, urlparse

import pytest
import yaml

from apps.agents.models import AgentConfig, AgentRun, ExternalUsage, RunEvent
from apps.agents.runs import RunReporter
from apps.content.models import BlogTopic
from apps.inbox import services as inbox
from apps.inbox.models import Draft, DraftVersion
from apps.policy.service import policy_for
from apps.publishing import connections, services
from apps.publishing import host as host_module
from apps.publishing.frontmatter import FrontmatterSettings, render_post
from apps.publishing.models import DraftPullRequest, GitHubConnection
from providers.git_host import FakeGitHost, NeedsReconnect, Unavailable
from tests.test_content_agent import post_json, responder

pytestmark = pytest.mark.django_db

BODY = "## Why it matters\n\nSome text.\n\n## Conclusion\n\nDone."
CONTENT = {"title": "How to plan a launch", "meta_description": "A short guide.", "slug": "how-to-plan-a-launch",
           "keywords": ["launch plan", "launch checklist"], "body_md": BODY}


@pytest.fixture
def gh():
    fake = FakeGitHost()
    host_module._fake = fake
    yield fake
    host_module._fake = None


@pytest.fixture
def conn(project, gh):
    return GitHubConnection.objects.create(project=project, installation_id=1, account="acme", repo="acme/site",
                                           base_branch="main", base_branch_protected=True, folder="content/blog",
                                           status=GitHubConnection.Status.READY)


def blog_draft(project, content=None, flags=None, status="new") -> Draft:
    draft = inbox.create_draft(project, agent_type="content", kind="blog_post", content=content or CONTENT,
                               result=None)
    draft.compliance_flags = flags or []
    draft.status = status
    draft.save()
    return draft


def create(client, draft, capture):
    with capture(execute=True):
        return client.post(f"/api/drafts/{draft.pk}/pull-request/")


def update(client, draft, capture):
    with capture(execute=True):
        return client.post(f"/api/drafts/{draft.pk}/pull-request/update/")


def detail(client, draft):
    return client.get(f"/api/drafts/{draft.pk}/").json()["pull_request"]


# --- AC-1: nothing changes without a connection --------------------------------------


def test_without_a_connection_there_is_no_pr_and_no_automatic_mode(client, project, gh):
    draft = blog_draft(project)
    assert detail(client, draft) is None
    assert client.post(f"/api/drafts/{draft.pk}/pull-request/").status_code == 409
    resp = client.patch("/api/agents/content/", {"publish_mode": "automatic"}, format="json")
    assert resp.status_code == 400
    assert client.get("/api/agents/content/").json()["automatic_available"] is False


def test_automatic_mode_needs_a_ready_connection_and_is_content_only(client, project, conn):
    assert client.patch("/api/agents/content/", {"publish_mode": "automatic"}, format="json").status_code == 200
    assert client.patch("/api/agents/x/", {"publish_mode": "automatic"}, format="json").status_code == 400


# --- AC-2: connecting ------------------------------------------------------------------


def test_connect_round_trip_saves_the_installation(client, user, project, gh):
    url = client.post("/api/github/connect/").json()["url"]
    state = parse_qs(urlparse(url).query)["state"][0]
    resp = client.get("/api/github/callback/", {"state": state, "code": "c", "installation_id": 1,
                                                "setup_action": "install"})
    assert resp.status_code == 302 and "github=connected" in resp["Location"]
    conn = GitHubConnection.objects.get(project=project)
    assert (conn.installation_id, conn.account, conn.status) == (1, "acme", "incomplete")


@pytest.mark.parametrize("change", ["bad_state", "not_theirs", "no_code"])
def test_connect_refuses_tampered_or_foreign_installations(client, project, gh, change):
    state = connections.connect_state(project.owner_id, project)
    params = {"state": state, "code": "c", "installation_id": 1}
    if change == "bad_state":
        params["state"] = state + "x"
    elif change == "not_theirs":
        params["installation_id"] = 999  # GitHub doesn't list it for this user
    else:
        params["code"] = ""
    resp = client.get("/api/github/callback/", params)
    assert "github=error" in resp["Location"]
    assert not GitHubConnection.objects.exists()


def test_an_org_install_waiting_for_approval_saves_nothing(client, project, gh):
    resp = client.get("/api/github/callback/", {"setup_action": "request"})
    assert "github=requested" in resp["Location"]
    assert not GitHubConnection.objects.exists()


def test_settings_save_checks_the_repo_branch_and_folder(client, project, gh):
    GitHubConnection.objects.create(project=project, installation_id=1)
    ok = {"repo": "acme/site", "base_branch": "main", "folder": "/content/blog/"}
    assert client.patch("/api/github/connection/", {**ok, "repo": "acme/other"}, format="json").status_code == 400
    assert client.patch("/api/github/connection/", {**ok, "base_branch": "nope"}, format="json").status_code == 400
    assert client.patch("/api/github/connection/", {**ok, "base_branch": "luka/x"}, format="json").status_code == 400
    assert client.patch("/api/github/connection/", {**ok, "folder": "../etc"}, format="json").status_code == 400
    assert client.patch("/api/github/connection/", {**ok, "folder": ".github"}, format="json").status_code == 400
    resp = client.patch("/api/github/connection/", ok, format="json")
    assert resp.status_code == 200
    assert resp.json()["folder"] == "content/blog" and resp.json()["status"] == "ready"
    assert resp.json()["base_branch_protected"] is True


def test_an_unprotected_base_branch_is_reported(client, project, gh):
    gh.repos["acme/site"].protected = set()
    GitHubConnection.objects.create(project=project, installation_id=1)
    resp = client.patch("/api/github/connection/", {"repo": "acme/site", "base_branch": "main"}, format="json")
    assert resp.json()["base_branch_protected"] is False


# --- AC-4, AC-5, AC-8, AC-13, AC-16: creating a PR ---------------------------------------


def test_create_pr_adds_one_file_on_a_new_branch(client, project, conn, gh, django_capture_on_commit_callbacks):
    draft = blog_draft(project, flags=[{"rule": "Claims", "excerpt": "best @everyone", "explanation": "Too strong"}])
    resp = create(client, draft, django_capture_on_commit_callbacks)
    assert resp.status_code == 202

    pr = detail(client, draft)
    assert (pr["state"], pr["number"]) == ("open", 1)
    assert pr["url"] == "https://github.com/acme/site/pull/1"
    repo = gh.repos["acme/site"]
    assert repo.branches["main"] == {}  # the base branch is untouched (AC-13)
    branch = repo.prs[0]["head"]
    assert branch.startswith("luka/") and repo.prs[0]["base"] == "main"
    assert list(repo.branches[branch]) == ["content/blog/how-to-plan-a-launch.md"]
    assert all(w[2].startswith("luka/") for w in gh.writes if w[0] in ("put_file", "delete_file", "ensure_branch"))

    body = repo.prs[0]["body"]  # AC-8
    assert "A short guide." in body and "how-to-plan-a-launch" in body and "launch checklist" in body
    assert "Too strong" in body and "@​everyone" in body  # flags listed, mentions neutralised
    assert f"/inbox/{draft.pk}?project={project.pk}" in body

    draft.refresh_from_db()
    assert draft.status == "new"  # AC-16: a PR never changes the draft's status


def test_the_file_has_frontmatter_body_and_disclaimer(project, conn):
    policy = policy_for(project)
    policy.blog_disclaimer = "Not advice."
    policy.save()
    fm = FrontmatterSettings(field_names={"description": "excerpt", "date": "pubDate"},
                             constant_fields=[{"key": "author", "value": "The Team"},
                                              {"key": "featured", "value": False}])
    content = {**CONTENT, "title": 'Quotes "and" colons: --- yes\nnewline'}
    text = render_post(content, fm, date(2026, 10, 15), policy.blog_disclaimer)
    head, body = text.split("\n---\n", 1)
    data = yaml.safe_load(head.removeprefix("---\n"))
    assert data == {"title": content["title"], "excerpt": "A short guide.", "slug": "how-to-plan-a-launch",
                    "keywords": ["launch plan", "launch checklist"], "pubDate": date(2026, 10, 15),
                    "author": "The Team", "featured": False}
    assert list(data)[:5] == ["title", "excerpt", "slug", "keywords", "pubDate"]
    assert body.strip().startswith("## Why it matters") and body.rstrip().endswith("*Not advice.*")
    # Already there: not added twice
    again = render_post({**content, "body_md": text.split("\n---\n", 1)[1]}, fm, date(2026, 10, 15), "Not advice.")
    assert again.count("Not advice.") == 1


def test_frontmatter_date_is_the_day_the_pr_is_created_and_survives_updates(
        client, project, conn, gh, django_capture_on_commit_callbacks):
    draft = blog_draft(project)
    create(client, draft, django_capture_on_commit_callbacks)
    row = DraftPullRequest.objects.get(draft=draft)
    row.post_date = date(2020, 1, 2)
    row.save()
    inbox.edit(draft, {"title": "A new title"})
    update(client, draft, django_capture_on_commit_callbacks)
    text = gh.repos["acme/site"].branches[row.branch]["content/blog/how-to-plan-a-launch.md"]
    assert "date: 2020-01-02" in text and "A new title" in text


def test_an_existing_file_on_the_base_branch_is_never_overwritten(
        client, project, conn, gh, django_capture_on_commit_callbacks):
    gh.repos["acme/site"].branches["main"]["content/blog/how-to-plan-a-launch.md"] = "theirs"
    draft = blog_draft(project)
    create(client, draft, django_capture_on_commit_callbacks)
    pr = detail(client, draft)
    assert pr["state"] == "failed" and "already exists" in pr["note"] and "slug" in pr["note"]
    assert gh.repos["acme/site"].branches["main"]["content/blog/how-to-plan-a-launch.md"] == "theirs"
    assert not gh.repos["acme/site"].prs and pr["can_create"] is True  # retry after changing the slug

    inbox.edit(draft, {"slug": "how-to-plan-a-launch-2"})
    create(client, draft, django_capture_on_commit_callbacks)
    assert detail(client, draft)["state"] == "open"


# --- AC-6: field settings and preview ----------------------------------------------------


def test_field_settings_are_validated(client, project, conn):
    base = {"repo": "acme/site", "base_branch": "main"}
    dup = {**base, "field_names": {"description": "title"}}
    assert client.patch("/api/github/connection/", dup, format="json").status_code == 400
    clash = {**base, "constant_fields": [{"key": "slug", "value": "x"}]}
    assert client.patch("/api/github/connection/", clash, format="json").status_code == 400
    bad_key = {**base, "constant_fields": [{"key": "a b", "value": "x"}]}
    assert client.patch("/api/github/connection/", bad_key, format="json").status_code == 400
    nested = {**base, "constant_fields": [{"key": "tags", "value": ["x"]}]}
    assert client.patch("/api/github/connection/", nested, format="json").status_code == 400
    ok = {**base, "field_names": {"description": "excerpt"}, "constant_fields": [{"key": "author", "value": "Me"}]}
    data = client.patch("/api/github/connection/", ok, format="json").json()
    assert data["field_names"]["description"] == "excerpt" and data["field_names"]["title"] == "title"


def test_preview_shows_unsaved_settings_on_the_latest_draft(client, project, conn):
    blog_draft(project)
    resp = client.post("/api/github/preview/", {"folder": "posts", "field_names": {"date": "published"},
                                                "constant_fields": [{"key": "featured", "value": True}]},
                       format="json").json()
    assert resp["path"] == "posts/how-to-plan-a-launch.md"
    assert "published:" in resp["frontmatter"] and "featured: true" in resp["frontmatter"]


def test_preview_uses_a_sample_without_drafts(client, project, conn):
    assert client.post("/api/github/preview/", {}, format="json").json()["from_draft"] is None


# --- AC-7: the slug field ----------------------------------------------------------------


@pytest.mark.parametrize("slug", ["Has Caps", "under_score", "trailing-", "a--b", "x" * 101, ""])
def test_slug_must_be_lowercase_words_and_hyphens(client, project, slug):
    draft = blog_draft(project)
    assert client.post(f"/api/drafts/{draft.pk}/edit/", {"content": {"slug": slug}}, format="json").status_code == 400


def test_changing_the_slug_renames_the_file_in_the_same_pr(client, project, conn, gh,
                                                           django_capture_on_commit_callbacks):
    draft = blog_draft(project)
    create(client, draft, django_capture_on_commit_callbacks)
    inbox.edit(draft, {"slug": "launch-planning"})
    update(client, draft, django_capture_on_commit_callbacks)
    repo = gh.repos["acme/site"]
    branch = repo.prs[0]["head"]
    assert list(repo.branches[branch]) == ["content/blog/launch-planning.md"]
    assert len(repo.prs) == 1


# --- AC-9, AC-10: automatic mode ---------------------------------------------------------


def run_content(project):
    from apps.agents.runs import create_run
    from apps.agents.tasks import run_agent_task

    run = create_run(project, "content")
    run_agent_task(run.id)
    run.refresh_from_db()
    return run


# Uses the topic's primary keyword where the SEO check looks for it, so the post has no flags.
CLEAN_POST = post_json(title="Queued topic A", body="Queued topic A, explained.\n\n## Queued topic A basics\nText.")


def automatic_project(project, lint=None):
    AgentConfig.objects.create(project=project, agent_type="content", config={"min_backlog": 0},
                               publish_mode="automatic")
    BlogTopic.objects.create(project=project, title="Queued topic A")


def test_automatic_mode_opens_the_pr_when_the_post_is_written(project, conn, gh, fake_anthropic):
    automatic_project(project)
    fake_anthropic(responder=responder(post=CLEAN_POST))
    run = run_content(project)
    assert run.status == "succeeded"
    draft = Draft.objects.get()
    row = DraftPullRequest.objects.get(draft=draft)
    assert row.state == "open" and len(gh.repos["acme/site"].prs) == 1


def test_automatic_mode_holds_flagged_posts(project, conn, gh, fake_anthropic, client):
    automatic_project(project)
    fake_anthropic(responder=responder(lint=[{"rule": "Claims", "excerpt": "x", "explanation": "y"}]))
    run_content(project)
    draft = Draft.objects.get()
    pr = detail(client, draft)
    assert pr["state"] == "held" and "Held for review" in pr["note"] and pr["can_create"] is True
    assert not gh.repos["acme/site"].prs


def test_seo_flags_hold_too(project, conn, gh):
    AgentConfig.objects.create(project=project, agent_type="content", publish_mode="automatic")
    draft = blog_draft(project, flags=[{"rule": "seo", "excerpt": "k", "explanation": "missing"}])
    run = AgentRun.objects.create(project=project, kind="content")
    services.after_draft_written(draft, run, RunReporter(run))
    assert DraftPullRequest.objects.get(draft=draft).state == "held"


def test_manual_mode_opens_nothing_on_its_own(project, conn, gh, fake_anthropic):
    AgentConfig.objects.create(project=project, agent_type="content", config={"min_backlog": 0})
    BlogTopic.objects.create(project=project, title="Queued topic A")
    fake_anthropic(responder=responder())
    run_content(project)
    assert not DraftPullRequest.objects.exists() and not gh.writes


# --- AC-11, AC-12: updates and no second PR ----------------------------------------------


def test_edits_wait_for_update_pr(client, project, conn, gh, django_capture_on_commit_callbacks):
    draft = blog_draft(project)
    create(client, draft, django_capture_on_commit_callbacks)
    writes = len(gh.writes)
    client.post(f"/api/drafts/{draft.pk}/edit/", {"content": {"title": "Edited"}}, format="json")
    assert len(gh.writes) == writes
    pr = detail(client, draft)
    assert pr["needs_update"] is True and pr["can_update"] is True

    assert update(client, draft, django_capture_on_commit_callbacks).status_code == 202
    repo = gh.repos["acme/site"]
    assert len(repo.prs) == 1 and repo.prs[0]["title"] == "Edited"
    assert "Edited" in repo.branches[repo.prs[0]["head"]]["content/blog/how-to-plan-a-launch.md"]
    assert detail(client, draft)["needs_update"] is False


def test_a_draft_never_gets_a_second_pr(client, project, conn, gh, django_capture_on_commit_callbacks):
    draft = blog_draft(project)
    create(client, draft, django_capture_on_commit_callbacks)
    assert client.post(f"/api/drafts/{draft.pk}/pull-request/").status_code == 409
    # A queued create blocks a double click
    other = blog_draft(project, content={**CONTENT, "slug": "other"})
    AgentRun.objects.create(project=project, kind="publish_pr", status="queued", params={"draft_id": other.pk})
    assert client.post(f"/api/drafts/{other.pk}/pull-request/").status_code == 409
    # Calling the service again directly also opens nothing new
    run = AgentRun.objects.create(project=project, kind="publish_pr")
    assert services.open_pull_request(draft, run, RunReporter(run)) is None
    assert len(gh.repos["acme/site"].prs) == 1


def test_a_retry_reuses_the_branch_and_pr_from_a_half_finished_attempt(project, conn, gh):
    draft = blog_draft(project)
    branch = services.branch_name(draft, CONTENT["slug"])
    repo = gh.repos["acme/site"]
    repo.branches[branch] = {"content/blog/how-to-plan-a-launch.md": "old"}
    repo.prs.append({"number": 1, "url": "https://github.com/acme/site/pull/1", "head": branch, "base": "main",
                     "title": "t", "body": "b", "state": "open"})
    run = AgentRun.objects.create(project=project, kind="publish_pr")
    row = services.open_pull_request(draft, run, RunReporter(run))
    assert row.state == "open" and row.number == 1 and len(repo.prs) == 1
    assert repo.branches[branch]["content/blog/how-to-plan-a-launch.md"] != "old"


# --- AC-14: failures ---------------------------------------------------------------------


def test_lost_access_marks_the_connection_and_offers_retry(client, project, conn, gh,
                                                           django_capture_on_commit_callbacks):
    gh.fail = NeedsReconnect()
    draft = blog_draft(project)
    create(client, draft, django_capture_on_commit_callbacks)
    pr = detail(client, draft)
    assert pr["state"] == "failed" and "Reconnect GitHub" in pr["note"]
    conn.refresh_from_db()
    assert conn.status == "needs_reconnect"
    assert client.get("/api/github/").json()["connection"]["status"] == "needs_reconnect"


def test_a_github_outage_fails_softly_and_can_be_retried(client, project, conn, gh,
                                                         django_capture_on_commit_callbacks):
    gh.fail = Unavailable()
    draft = blog_draft(project)
    resp = create(client, draft, django_capture_on_commit_callbacks)
    run = AgentRun.objects.get(pk=resp.json()["id"])
    assert run.status != "failed"
    pr = detail(client, draft)
    assert pr["state"] == "failed" and "Try again" in pr["note"] and pr["can_create"] is True
    gh.fail = None
    create(client, draft, django_capture_on_commit_callbacks)
    assert detail(client, draft)["state"] == "open"


def test_automatic_failure_still_lands_the_draft(project, conn, gh, fake_anthropic):
    automatic_project(project)
    gh.fail = Unavailable()
    fake_anthropic(responder=responder(post=CLEAN_POST))
    run = run_content(project)
    assert run.status != "failed" and Draft.objects.count() == 1
    assert DraftPullRequest.objects.get().state == "failed"


def test_a_merged_and_deleted_branch_explains_itself(client, project, conn, gh, django_capture_on_commit_callbacks):
    draft = blog_draft(project)
    create(client, draft, django_capture_on_commit_callbacks)
    repo = gh.repos["acme/site"]
    del repo.branches[repo.prs[0]["head"]]
    inbox.edit(draft, {"title": "x"})
    update(client, draft, django_capture_on_commit_callbacks)
    pr = detail(client, draft)
    assert pr["state"] == "failed" and "merged or deleted" in pr["note"] and pr["number"] == 1


# --- AC-15: only new blog posts ----------------------------------------------------------


def test_dismissed_and_non_blog_drafts_get_no_pr(client, project, conn, gh):
    dismissed = blog_draft(project, status="dismissed")
    assert detail(client, dismissed)["can_create"] is False
    assert client.post(f"/api/drafts/{dismissed.pk}/pull-request/").status_code == 409
    reply = Draft.objects.create(project=project, agent_type="reddit", kind="reddit_comment")
    reply.current_version = DraftVersion.objects.create(draft=reply, n=1, source="ai_initial", content={"body": "x"})
    reply.save()
    assert detail(client, reply) is None
    assert client.post(f"/api/drafts/{reply.pk}/pull-request/").status_code == 409
    assert not gh.writes


# --- AC-17: disconnecting ----------------------------------------------------------------


def test_disconnect_switches_to_manual_and_leaves_github_alone(client, project, conn, gh,
                                                                django_capture_on_commit_callbacks):
    AgentConfig.objects.create(project=project, agent_type="content", publish_mode="automatic")
    draft = blog_draft(project)
    create(client, draft, django_capture_on_commit_callbacks)
    writes = list(gh.writes)
    assert client.delete("/api/github/connection/").status_code == 204
    assert gh.writes == writes and len(gh.repos["acme/site"].prs) == 1
    assert AgentConfig.objects.get(project=project, agent_type="content").publish_mode == "manual"
    pr = detail(client, draft)
    assert pr["url"] == "https://github.com/acme/site/pull/1" and pr["can_update"] is False
    assert client.post(f"/api/drafts/{draft.pk}/pull-request/").status_code == 409


# --- AC-18: the trail, without content -----------------------------------------------------


def test_the_trail_has_repo_and_pr_number_but_no_content(client, project, conn, gh, caplog,
                                                         django_capture_on_commit_callbacks):
    caplog.set_level(logging.INFO)
    draft = blog_draft(project)
    resp = create(client, draft, django_capture_on_commit_callbacks)
    run = AgentRun.objects.get(pk=resp.json()["id"])
    events = RunEvent.objects.filter(run=run)
    done = events.get(data__purpose="create_pr")
    assert done.data["resource_id"] == "acme/site" and done.data["pr_number"] == 1
    usage = ExternalUsage.objects.get(agent_run=run)
    assert (usage.provider, usage.external_run_id) == ("github", "1")
    for text in ("Some text.", "A short guide.", CONTENT["title"]):
        assert not any(text in str(e.data) or text in e.message for e in events)
        assert text not in caplog.text


def test_the_callback_falls_back_to_the_state_kept_in_the_session(client, project, gh):
    client.post("/api/github/connect/")
    resp = client.get("/api/github/callback/", {"code": "c", "installation_id": 1, "setup_action": "install"})
    assert "github=connected" in resp["Location"]
    assert GitHubConnection.objects.filter(project=project).exists()


def test_without_any_state_nothing_is_saved(client, project, gh):
    resp = client.get("/api/github/callback/", {"code": "c", "installation_id": 1})
    assert "github=error" in resp["Location"] and not GitHubConnection.objects.exists()
