"""Opening and updating a blog draft's pull request.

Every path goes through `open_pull_request` / `update_pull_request`: the "Create PR" button,
its retry, and automatic mode inside a content run. So the checks (blog posts only, no second
PR, never overwrite a file on the base branch) and the run trail are the same whichever way a
PR is opened. Luka writes only to its own `luka/` branches and never merges; GitHub's branch
protection on the base branch backs that up (docs/security-patterns.md §7).
"""

import logging
import os
import time
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.agents.external import record_external
from apps.agents.models import AgentConfig, AgentRun, AgentType
from apps.agents.runs import RunReporter
from apps.inbox.models import Draft, DraftKind
from apps.policy.service import policy_for
from providers.git_host import BRANCH_PREFIX, GitHostError, NeedsReconnect, NotFound

from .connections import connection_for, frontmatter_settings, mark_needs_reconnect
from .frontmatter import post_path, render_post
from .host import get_git_host
from .models import DraftPullRequest, GitHubConnection

log = logging.getLogger(__name__)

ACTIVE = AgentRun.ACTIVE
PENDING_TIMEOUT = timedelta(minutes=10)


class PublishStateError(Exception):
    """The draft can't get (or update) a PR right now; the message says why. The API answers 409."""


class _Clash(Exception):
    """The post's file name is already taken on the base branch."""

    def __init__(self, path: str):
        super().__init__(path)
        self.path = path


# --- what a draft can do ---------------------------------------------------------------


def pr_row(draft: Draft) -> DraftPullRequest | None:
    return DraftPullRequest.objects.filter(draft=draft).first()


def publish_running(draft: Draft) -> bool:
    """A create or update is queued or running for this draft."""
    return AgentRun.objects.filter(kind=AgentRun.Kind.PUBLISH_PR, status__in=ACTIVE,
                                   params__draft_id=draft.pk).exists()


def create_blocker(draft: Draft, conn: GitHubConnection | None, row: DraftPullRequest | None) -> str:
    """Why "Create PR" isn't available, or "" when it is."""
    if draft.kind != DraftKind.BLOG_POST:
        return "Only blog posts can become pull requests"
    if draft.status != Draft.Status.NEW:
        return f"Can't open a pull request for a draft that is {draft.status}"
    if conn is None or not conn.is_ready:
        return "Connect a GitHub repository in Settings first"
    if row is not None and row.has_pr:
        return "This draft already has a pull request"
    # A create that died mid-way (a worker restart) mustn't block the draft forever.
    if (row is not None and row.state == DraftPullRequest.State.PENDING
            and row.updated_at > timezone.now() - PENDING_TIMEOUT):
        return "A pull request is already being opened"
    return ""


def update_blocker(draft: Draft, conn: GitHubConnection | None, row: DraftPullRequest | None) -> str:
    """Why "Update PR" isn't available, or "" when it is."""
    if row is None or not row.has_pr:
        return "This draft has no pull request yet"
    if draft.status != Draft.Status.NEW:
        return f"Can't update the pull request of a draft that is {draft.status}"
    if conn is None or not conn.is_ready:
        return "Connect a GitHub repository in Settings first"
    return ""


def request(draft: Draft, action: str) -> AgentRun:
    """Queue a create ("create") or update ("update") for a draft, as a publish run.

    The draft row is locked while checking, so two clicks can't both pass: the second sees
    the first's run and is refused.

    Raises:
        PublishStateError: The action isn't available for this draft right now.
    """
    from .tasks import publish_pr_task

    with transaction.atomic():
        draft = Draft.objects.select_for_update().get(pk=draft.pk)
        conn, row = connection_for(draft.project), pr_row(draft)
        blocker = (create_blocker if action == "create" else update_blocker)(draft, conn, row)
        if not blocker and publish_running(draft):
            blocker = "This draft's pull request is already being updated"
        if blocker:
            raise PublishStateError(blocker)
        run = AgentRun.objects.create(project=draft.project, kind=AgentRun.Kind.PUBLISH_PR,
                                      params={"draft_id": draft.pk, "action": action})
        transaction.on_commit(lambda: publish_pr_task.delay(run.id))
    return run


# --- automatic mode --------------------------------------------------------------------


def automatic(project) -> bool:
    """The project's Content Agent opens PRs on its own."""
    return AgentConfig.objects.filter(project=project, agent_type=AgentType.CONTENT,
                                      publish_mode=AgentConfig.PublishMode.AUTOMATIC).exists()


def after_draft_written(draft: Draft, run: AgentRun, reporter: RunReporter) -> None:
    """Automatic mode: open the PR for a freshly written post, or hold it if it has flags.

    Called by the content run after linting. Never raises: a failure is recorded on the
    draft and in the run trail, and the draft stays in the inbox either way.
    """
    if not automatic(draft.project):
        return
    if draft.compliance_flags:
        n = len(draft.compliance_flags)
        DraftPullRequest.objects.update_or_create(
            draft=draft, defaults={"project": draft.project, "state": DraftPullRequest.State.HELD,
                                   "note": f"Held for review: {n} flag{'s' if n != 1 else ''} to check first"})
        reporter.event(f"Held draft #{draft.pk} for review instead of opening a PR", draft_id=draft.pk, flags=n)
        return
    open_pull_request(draft, run, reporter)


# --- the work --------------------------------------------------------------------------


def _neutralise_mentions(text: str) -> str:
    """Stop model-written text from @-mentioning people in the PR (GitHub would notify them)."""
    return text.replace("@", "@​")


def pr_body(draft: Draft, content: dict) -> str:
    """The PR description: the SEO fields, every flag on the draft, and a link back to Luka."""
    flags = draft.compliance_flags or []
    lines = [
        f"**Meta description:** {content['meta_description']}",
        f"**Slug:** `{content['slug']}`",
        f"**Keywords:** {', '.join(content['keywords']) or '—'}",
        "",
        f"**Flags ({len(flags)}):**" if flags else "**Flags:** none",
    ]
    for f in flags:
        excerpt = f" — “{f.get('excerpt', '')}”" if f.get("excerpt") else ""
        lines.append(f"- **{f.get('rule', 'flag')}:** {f.get('explanation', '')}{excerpt}")
    link = f"{settings.LUKA_APP_URL}/inbox/{draft.pk}?project={draft.project_id}"
    lines += ["", f"[Open this draft in Luka]({link})", "",
              "_Opened by Luka. Review and merge when you're ready: Luka never merges or pushes to this branch's "
              "base._"]
    return _neutralise_mentions("\n".join(lines))


def pr_title(content: dict) -> str:
    return _neutralise_mentions(" ".join(content["title"].split()))[:250]


def branch_name(draft: Draft, slug: str) -> str:
    return f"{BRANCH_PREFIX}{draft.pk}-{slug}"[:100].rstrip("-")


def safe_pr_url(repo: str, url: str) -> str:
    """The PR's link, only if it's the https GitHub page for this repository's PR."""
    return url if url.startswith(f"https://github.com/{repo}/pull/") else ""


def _claim(draft: Draft, run: AgentRun) -> DraftPullRequest | None:
    """Lock the draft and take its PR row for a create; None if it already has a PR."""
    with transaction.atomic():
        Draft.objects.select_for_update().get(pk=draft.pk)
        row, _ = DraftPullRequest.objects.get_or_create(
            draft=draft, defaults={"project": draft.project, "state": DraftPullRequest.State.PENDING})
        if row.has_pr:
            return None
        row.state = DraftPullRequest.State.PENDING
        row.note = ""
        row.save(update_fields=["state", "note", "updated_at"])
        return row


def _fail(row: DraftPullRequest, note: str) -> None:
    row.state = DraftPullRequest.State.FAILED
    row.note = note[:300]
    row.save(update_fields=["state", "note", "updated_at"])


def _report_failure(run, reporter, conn, row, purpose: str, started: float, exc: Exception) -> None:
    """Record a failed GitHub step on the draft and in the trail, as the user should read it."""
    duration = int((time.monotonic() - started) * 1000)
    if isinstance(exc, _Clash):
        note = (f"A file named {os.path.basename(exc.path)} already exists in the repository. "
                "Change the slug and try again.")
        status = "file_exists"
    else:
        note, status = exc.reason, type(exc).__name__
        if isinstance(exc, NeedsReconnect):
            mark_needs_reconnect(conn)
    _fail(row, note)
    record_external(run, reporter, provider="github", purpose=purpose, message=f"GitHub {purpose.replace('_', ' ')}",
                    resource_id=row.repo or conn.repo, status=status, duration_ms=duration, error=note,
                    draft_id=row.draft_id)
    if not isinstance(exc, (_Clash, NeedsReconnect, NotFound)):
        # Unexpected: GitHub erred or we sent something it refused. Worth an issue.
        log.error("github %s failed for draft %s", purpose, row.draft_id, exc_info=exc)


def open_pull_request(draft: Draft, run: AgentRun, reporter: RunReporter) -> DraftPullRequest | None:
    """Create the branch, the post's file and the PR. Safe to retry: an existing branch, file
    or open PR from an earlier attempt is reused rather than duplicated.

    Returns the row (open or failed), or None when the draft isn't eligible. Never raises a
    GitHub error: failures are recorded on the row and in the run trail.
    """
    conn = connection_for(draft.project)
    if blocker := create_blocker(draft, conn, None):
        reporter.warning(f"Didn't open a PR for draft #{draft.pk}: {blocker}", draft_id=draft.pk)
        return None
    row = _claim(draft, run)
    if row is None:
        reporter.event(f"Draft #{draft.pk} already has a pull request", draft_id=draft.pk)
        return None
    content = draft.current_version.content
    path = post_path(conn.folder, content["slug"])
    branch = row.branch or branch_name(draft, content["slug"])
    post_date = row.post_date or timezone.localdate()
    row.repo = conn.repo
    reporter.step(f"Opening a pull request for draft #{draft.pk} in {conn.repo}", draft_id=draft.pk, repo=conn.repo)
    host, inst, started = get_git_host(), conn.installation_id, time.monotonic()
    try:
        base = host.get_branch(inst, conn.repo, conn.base_branch)
        if host.file_sha(inst, conn.repo, path, conn.base_branch) is not None:
            raise _Clash(path)
        host.ensure_branch(inst, conn.repo, branch, base.sha)
        text = render_post(content, frontmatter_settings(conn), post_date, policy_for(draft.project).blog_disclaimer)
        existing = host.file_sha(inst, conn.repo, path, branch)
        host.put_file(inst, conn.repo, branch, path, text, f"Add blog post: {pr_title(content)}", sha=existing)
        pr = host.find_open_pr(inst, conn.repo, branch) or host.create_pr(
            inst, conn.repo, branch, conn.base_branch, pr_title(content), pr_body(draft, content))
    except (GitHostError, _Clash) as exc:
        row.branch, row.post_date = branch, post_date
        row.save(update_fields=["repo", "branch", "post_date", "updated_at"])
        _report_failure(run, reporter, conn, row, "create_pr", started, exc)
        return row
    row.state, row.branch, row.file_path, row.post_date = DraftPullRequest.State.OPEN, branch, path, post_date
    row.number, row.url, row.note = pr.number, safe_pr_url(conn.repo, pr.url), ""
    row.pushed_version = draft.current_version
    row.save()
    record_external(run, reporter, provider="github", purpose="create_pr",
                    message=f"Opened pull request #{pr.number} in {conn.repo}", resource_id=conn.repo,
                    external_run_id=str(pr.number), status="ok", items=1,
                    duration_ms=int((time.monotonic() - started) * 1000), draft_id=draft.pk, pr_number=pr.number)
    log.info("opened PR %s in %s for draft %s", pr.number, conn.repo, draft.pk)
    return row


def update_pull_request(draft: Draft, run: AgentRun, reporter: RunReporter) -> DraftPullRequest | None:
    """Push the draft's current version to its PR's branch and refresh the description.

    A changed slug renames the file in the same PR: the new file is added and the old one
    removed, on Luka's branch only. The new name must not already exist on the base branch.
    Never raises a GitHub error (see `open_pull_request`).
    """
    conn, row = connection_for(draft.project), pr_row(draft)
    if blocker := update_blocker(draft, conn, row):
        reporter.warning(f"Didn't update the PR for draft #{draft.pk}: {blocker}", draft_id=draft.pk)
        return None
    content = draft.current_version.content
    folder = os.path.dirname(row.file_path)
    path = post_path(folder, content["slug"])
    reporter.step(f"Updating pull request #{row.number} for draft #{draft.pk}", draft_id=draft.pk, repo=row.repo)
    host, inst, started = get_git_host(), conn.installation_id, time.monotonic()
    text = render_post(content, frontmatter_settings(conn), row.post_date or timezone.localdate(),
                       policy_for(draft.project).blog_disclaimer)
    message = f"Update blog post: {pr_title(content)}"
    try:
        if path != row.file_path:
            if host.file_sha(inst, row.repo, path, conn.base_branch) is not None:
                raise _Clash(path)
            host.put_file(inst, row.repo, row.branch, path, text, message,
                          sha=host.file_sha(inst, row.repo, path, row.branch))
            if old := host.file_sha(inst, row.repo, row.file_path, row.branch):
                host.delete_file(inst, row.repo, row.branch, row.file_path, old, message)
        else:
            host.put_file(inst, row.repo, row.branch, path, text, message,
                          sha=host.file_sha(inst, row.repo, path, row.branch))
        host.update_pr(inst, row.repo, row.number, pr_title(content), pr_body(draft, content))
    except NotFound as exc:
        exc.reason = "The pull request's branch is gone: it may have been merged or deleted on GitHub."
        _report_failure(run, reporter, conn, row, "update_pr", started, exc)
        return row
    except (GitHostError, _Clash) as exc:
        _report_failure(run, reporter, conn, row, "update_pr", started, exc)
        return row
    row.state, row.file_path, row.note = DraftPullRequest.State.OPEN, path, ""
    row.pushed_version = draft.current_version
    row.save()
    record_external(run, reporter, provider="github", purpose="update_pr",
                    message=f"Updated pull request #{row.number} in {row.repo}", resource_id=row.repo,
                    external_run_id=str(row.number), status="ok", items=1,
                    duration_ms=int((time.monotonic() - started) * 1000), draft_id=draft.pk, pr_number=row.number)
    log.info("updated PR %s in %s for draft %s", row.number, row.repo, draft.pk)
    return row


# --- what the detail pane shows --------------------------------------------------------


def pull_request_info(draft: Draft) -> dict | None:
    """The draft's PR state for the detail pane, or None when nothing about PRs applies."""
    if draft.kind != DraftKind.BLOG_POST:
        return None
    conn = connection_for(draft.project)
    row = pr_row(draft)
    if conn is None and row is None:
        return None
    busy = publish_running(draft)
    return {
        "state": row.state if row else None,
        "number": row.number if row else None,
        "url": row.url if row else "",
        "repo": row.repo if row else (conn.repo if conn else ""),
        "note": row.note if row else "",
        "busy": busy,
        "can_create": not busy and not create_blocker(draft, conn, row),
        "needs_update": bool(row and row.has_pr and row.pushed_version_id != draft.current_version_id),
        "can_update": not busy and not update_blocker(draft, conn, row),
    }
