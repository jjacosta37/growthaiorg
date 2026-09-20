import pytest

from llm import client as llm_client

# --- Tenancy -----------------------------------------------------------------------------
# Projects belong to users, so a test needs both. `user`/`project`/`client` are the caller;
# the `other_*` set is a second tenant, used to prove isolation.


def _make_user(username):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(username, password="pw")


def _make_client(user):
    from rest_framework.test import APIClient

    c = APIClient()
    c.force_authenticate(user)
    return c


@pytest.fixture
def user(db):
    return _make_user("me")


@pytest.fixture
def project(db, user):
    from apps.core.models import Project

    return Project.objects.create(owner=user, name="Acme")


@pytest.fixture
def client(db, user, project):
    """Authenticated as `user`, with `project` selected.

    The session is primed so the client doesn't depend on "first project wins" — tests that
    create a second project still act on `project` unless they switch explicitly.
    """
    c = _make_client(user)
    session = c.session
    session["project_id"] = project.pk
    session.save()
    c.cookies["sessionid"] = session.session_key
    return c


@pytest.fixture
def other_user(db):
    return _make_user("someone-else")


@pytest.fixture
def other_project(db, other_user):
    from apps.core.models import Project

    return Project.objects.create(owner=other_user, name="Globex")


@pytest.fixture
def other_client(db, other_user, other_project):
    c = _make_client(other_user)
    session = c.session
    session["project_id"] = other_project.pk
    session.save()
    c.cookies["sessionid"] = session.session_key
    return c


@pytest.fixture
def fake_anthropic():
    """Install a FakeAnthropic: `fake = fake_anthropic(msg1, msg2, ...)`."""
    from tests.fakes import FakeAnthropic

    installed = []

    def install(*responses, responder=None):
        fake = FakeAnthropic(*responses, responder=responder)
        llm_client.set_client(fake)
        installed.append(fake)
        return fake

    yield install
    llm_client.set_client(None)


@pytest.fixture
def prompts_tmp(tmp_path, settings):
    """Point PROMPTS_DIR at a temp dir holding a copy of the guardrails file."""
    from pathlib import Path

    from llm.prompts import guardrails_template

    (tmp_path / "_system").mkdir()
    src = Path(settings.BASE_DIR) / "prompts" / "_system" / "guardrails.md"
    (tmp_path / "_system" / "guardrails.md").write_text(src.read_text())
    settings.PROMPTS_DIR = tmp_path
    guardrails_template.cache_clear()
    yield tmp_path
    guardrails_template.cache_clear()


def write_prompt(root, task, version, frontmatter, system, user):
    d = root.joinpath(*task.split("."))
    d.mkdir(parents=True, exist_ok=True)
    body = f"---\n{frontmatter.strip()}\n---\n=== system ===\n{system}\n=== user ===\n{user}\n"
    (d / f"{version}.md").write_text(body)
