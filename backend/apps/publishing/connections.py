"""Connecting a project to a GitHub repository, and the settings that shape its post files.

The install round trip is where a tenant could try to claim someone else's installation: the
browser comes back from GitHub with an `installation_id` anyone can edit. So the callback
needs a signed `state` (this user, this project, recently), and an OAuth code proving the user
can see that installation on GitHub. Both are checked before anything is saved.
"""

import logging

from django.core import signing
from django.db import transaction

from apps.agents.models import AgentConfig, AgentType
from apps.core.models import Project
from providers.git_host import BRANCH_PREFIX, GitHostError, NeedsReconnect, Repo

from .frontmatter import FrontmatterSettings, clean_folder
from .host import get_git_host
from .models import GitHubConnection

log = logging.getLogger(__name__)

STATE_SALT = "luka.publishing.github-connect"
STATE_MAX_AGE = 15 * 60


class ConnectError(Exception):
    """Connecting or saving failed for a reason the user can act on; the message says which."""


def connection_for(project: Project) -> GitHubConnection | None:
    return GitHubConnection.objects.filter(project=project).first()


def connect_state(user_id: int, project: Project) -> str:
    """A signed token tying the GitHub round trip to this user and project."""
    return signing.dumps({"u": user_id, "p": project.pk}, salt=STATE_SALT)


def complete_install(user, state: str, code: str, installation_id: int) -> GitHubConnection:
    """Save the installation for the project named in `state`, after GitHub confirms it's the user's.

    Reconnecting keeps the repository, branch, folder and field settings, and is ready again
    as soon as the repository is still reachable.

    Raises:
        ConnectError: A bad or expired state, a project the user doesn't own, or an
            installation GitHub doesn't list for this user.
    """
    try:
        data = signing.loads(state, salt=STATE_SALT, max_age=STATE_MAX_AGE)
    except signing.BadSignature:
        raise ConnectError("The GitHub connection link expired. Try connecting again.") from None
    if data.get("u") != user.pk:
        raise ConnectError("This GitHub connection was started by another account")
    project = Project.objects.filter(pk=data.get("p"), owner=user).first()
    if project is None:
        raise ConnectError("This GitHub connection was started by another account")
    if not code:
        raise ConnectError("GitHub didn't send an authorisation code. Check the app's settings and try again.")
    try:
        installation = get_git_host().verify_installation(code, installation_id)
    except GitHostError as exc:
        raise ConnectError(exc.reason) from exc
    conn, _ = GitHubConnection.objects.update_or_create(
        project=project, defaults={"installation_id": installation.id, "account": installation.account})
    conn.status = GitHubConnection.Status.INCOMPLETE
    if conn.repo:
        try:
            refresh_base_branch(conn)
            conn.status = GitHubConnection.Status.READY
        except GitHostError:
            log.info("github reconnect for project %s: saved repository not reachable yet", project.pk)
    conn.save()
    log.info("github connected for project %s (installation %s)", project.pk, installation.id)
    return conn


def list_repos(conn: GitHubConnection) -> list[Repo]:
    """The repositories the user granted, marking the connection when access is gone.

    Raises:
        GitHostError: GitHub refused or failed.
    """
    try:
        return get_git_host().list_repos(conn.installation_id)
    except NeedsReconnect:
        mark_needs_reconnect(conn)
        raise


def refresh_base_branch(conn: GitHubConnection) -> None:
    """Re-read whether the base branch exists and is protected.

    Raises:
        GitHostError: The branch is gone or GitHub refused.
    """
    branch = get_git_host().get_branch(conn.installation_id, conn.repo, conn.base_branch)
    conn.base_branch_protected = branch.protected


def save_settings(conn: GitHubConnection, *, repo: str, base_branch: str, folder: str,
                  field_names: dict, constant_fields: list) -> GitHubConnection:
    """Validate and save where posts go and how their frontmatter is named. Ready once valid.

    Raises:
        ConnectError: The repository isn't granted, the branch is missing or Luka's own, the
            folder or field settings are invalid, or GitHub refused.
        pydantic.ValidationError: The field settings are malformed (the view reports both).
    """
    fm = FrontmatterSettings(field_names=field_names, constant_fields=constant_fields)
    try:
        folder = clean_folder(folder)
    except ValueError as exc:
        raise ConnectError(str(exc)) from None
    base_branch = base_branch.strip()
    if not base_branch or base_branch.startswith(BRANCH_PREFIX):
        raise ConnectError(f"Choose the branch your site deploys from, not one of Luka's ({BRANCH_PREFIX}…)")
    try:
        repos = {r.full_name: r for r in list_repos(conn)}
        if repo not in repos:
            raise ConnectError("Luka can't see that repository. Grant it access on GitHub first.")
        conn.repo, conn.base_branch = repo, base_branch
        refresh_base_branch(conn)
    except GitHostError as exc:
        raise ConnectError(exc.reason) from exc
    conn.folder = folder
    conn.field_names = fm.field_names
    conn.constant_fields = [c.model_dump() for c in fm.constant_fields]
    conn.status = GitHubConnection.Status.READY
    conn.save()
    return conn


def frontmatter_settings(conn: GitHubConnection | None) -> FrontmatterSettings:
    """The saved field settings (defaults when there is no connection)."""
    if conn is None:
        return FrontmatterSettings()
    return FrontmatterSettings(field_names=conn.field_names, constant_fields=conn.constant_fields)


def mark_needs_reconnect(conn: GitHubConnection) -> None:
    if conn.status != GitHubConnection.Status.NEEDS_RECONNECT:
        conn.status = GitHubConnection.Status.NEEDS_RECONNECT
        conn.save(update_fields=["status", "updated_at"])
        log.warning("github access lost for project %s (installation %s)", conn.project_id, conn.installation_id)


@transaction.atomic
def disconnect(project: Project) -> None:
    """Forget the connection and switch the Content Agent back to manual.

    Nothing on GitHub changes: open PRs and branches stay, and drafts keep their PR links.
    The app stays installed on GitHub, since another project may use the same installation.
    """
    GitHubConnection.objects.filter(project=project).delete()
    AgentConfig.objects.filter(project=project, agent_type=AgentType.CONTENT).update(
        publish_mode=AgentConfig.PublishMode.MANUAL)
    log.info("github disconnected for project %s", project.pk)


def can_automate(project: Project) -> bool:
    """Automatic mode needs a ready connection."""
    conn = connection_for(project)
    return conn is not None and conn.is_ready
