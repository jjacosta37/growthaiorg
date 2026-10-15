from django.db import models


class GitHubConnection(models.Model):
    """A project's link to one GitHub repository, through the Luka GitHub App.

    Only the installation id is stored: access tokens are minted per step and never saved.
    `field_names` maps the standard frontmatter fields to the names the site expects, and
    `constant_fields` are added to every post (apps/publishing/frontmatter.py validates both).
    """

    class Status(models.TextChoices):
        INCOMPLETE = "incomplete"  # installed; repository, branch or folder not chosen yet
        READY = "ready"
        NEEDS_RECONNECT = "needs_reconnect"  # GitHub refused a call: uninstalled, suspended or access removed

    project = models.OneToOneField("core.Project", on_delete=models.CASCADE, related_name="github_connection")
    installation_id = models.BigIntegerField()
    account = models.CharField(max_length=100, blank=True)  # the GitHub user or organisation
    # Repositories the connecting user could push to on GitHub when they connected. The
    # installation may reach more, but a project can only be pointed at one of these.
    allowed_repos = models.JSONField(default=list, blank=True)
    repo = models.CharField(max_length=200, blank=True)  # "owner/name"
    base_branch = models.CharField(max_length=200, blank=True)
    base_branch_protected = models.BooleanField(default=False)
    folder = models.CharField(max_length=200, blank=True)
    field_names = models.JSONField(default=dict, blank=True)  # {standard field: name in the file}
    constant_fields = models.JSONField(default=list, blank=True)  # [{key, value}]
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.INCOMPLETE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.project} → {self.repo or self.account}"

    @property
    def is_ready(self) -> bool:
        return self.status == self.Status.READY


class DraftPullRequest(models.Model):
    """The pull request opened (or held, or being opened) for one blog draft.

    One row per draft, enforced in the database, so no path can open a second PR. The row
    outlives a disconnect: the draft keeps its link to a PR that still exists on GitHub.
    """

    class State(models.TextChoices):
        HELD = "held"  # automatic mode skipped it because the draft has flags
        PENDING = "pending"  # a create is running
        OPEN = "open"
        FAILED = "failed"  # the last create or update failed; `error` says why

    project = models.ForeignKey("core.Project", on_delete=models.CASCADE, related_name="pull_requests")
    draft = models.OneToOneField("inbox.Draft", on_delete=models.CASCADE, related_name="pull_request")
    state = models.CharField(max_length=20, choices=State.choices)
    repo = models.CharField(max_length=200, blank=True)
    branch = models.CharField(max_length=255, blank=True)
    file_path = models.CharField(max_length=500, blank=True)
    number = models.PositiveIntegerField(null=True, blank=True)
    url = models.URLField(max_length=500, blank=True)  # https://github.com/... only (services.pr_url)
    post_date = models.DateField(null=True, blank=True)  # the frontmatter date: when the PR was first created
    pushed_version = models.ForeignKey("inbox.DraftVersion", on_delete=models.SET_NULL, null=True, blank=True,
                                       related_name="+")
    note = models.CharField(max_length=300, blank=True)  # why it was held, or the last failure (our own text)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"draft {self.draft_id} PR {self.number or '-'} ({self.state})"

    @property
    def has_pr(self) -> bool:
        return self.number is not None
