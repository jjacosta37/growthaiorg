from django.db import models


class AgentType(models.TextChoices):
    REDDIT = "reddit"
    CONTENT = "content"
    X = "x"


class AgentConfig(models.Model):
    """Per-agent settings, editable in the UI. `config` is validated by the agent's Pydantic model."""

    class PublishMode(models.TextChoices):
        MANUAL = "manual"  # drafts land in the inbox; the only mode for the MVP

    project = models.ForeignKey("core.Project", on_delete=models.CASCADE, related_name="agent_configs")
    agent_type = models.CharField(max_length=20, choices=AgentType.choices)
    enabled = models.BooleanField(default=False)
    cron = models.CharField(max_length=100, default="0 */6 * * *")
    config = models.JSONField(default=dict, blank=True)
    publish_mode = models.CharField(max_length=20, choices=PublishMode.choices, default=PublishMode.MANUAL)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["project", "agent_type"], name="uniq_agent_per_project")]

    def __str__(self):
        return f"{self.project} {self.agent_type}"

    @classmethod
    def for_project(cls, project, agent_type: str) -> "AgentConfig":
        """Get or create, using the agent's registered default schedule for new configs."""
        from .registry import get

        try:
            default_cron = get(agent_type).default_cron
        except KeyError:
            default_cron = cls._meta.get_field("cron").default
        obj, _ = cls.objects.get_or_create(project=project, agent_type=agent_type,
                                           defaults={"cron": default_cron})
        return obj


class AgentRun(models.Model):
    """One execution of a pipeline: an agent run, onboarding, a recrawl, or a single regeneration."""

    class Kind(models.TextChoices):
        ONBOARDING = "onboarding"
        RECRAWL = "recrawl"
        REGENERATE_DOC = "regenerate_doc"
        REDDIT = "reddit"
        CONTENT = "content"
        X = "x"
        REGENERATE_DRAFT = "regenerate_draft"

    class Trigger(models.TextChoices):
        SCHEDULED = "scheduled"
        MANUAL = "manual"

    class Status(models.TextChoices):
        QUEUED = "queued"
        RUNNING = "running"
        WAITING_BATCH = "waiting_batch"
        SUCCEEDED = "succeeded"
        PARTIAL = "partial"  # finished, but some steps failed (see events)
        FAILED = "failed"

    ACTIVE = (Status.QUEUED, Status.RUNNING, Status.WAITING_BATCH)

    project = models.ForeignKey("core.Project", on_delete=models.CASCADE, related_name="runs")
    kind = models.CharField(max_length=30, choices=Kind.choices)
    trigger = models.CharField(max_length=20, choices=Trigger.choices, default=Trigger.MANUAL)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED)
    current_step = models.CharField(max_length=255, blank=True)
    params = models.JSONField(default=dict, blank=True)
    stats = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["project", "kind", "-created_at"])]

    def __str__(self):
        return f"{self.kind} #{self.pk} {self.status}"

    @property
    def is_active(self) -> bool:
        return self.status in self.ACTIVE


class RunEvent(models.Model):
    """Progress log for a run. Drives the progress UI and the sidebar status line."""

    class Level(models.TextChoices):
        INFO = "info"
        SUCCESS = "success"
        WARNING = "warning"
        ERROR = "error"

    run = models.ForeignKey(AgentRun, on_delete=models.CASCADE, related_name="events")
    level = models.CharField(max_length=10, choices=Level.choices, default=Level.INFO)
    message = models.CharField(max_length=500)
    data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"[{self.level}] {self.message}"


class ExternalUsage(models.Model):
    """Spend on non-LLM providers (Apify rendering and Reddit scraping), for in-app cost stats."""

    project = models.ForeignKey("core.Project", on_delete=models.CASCADE, related_name="external_usage")
    agent_run = models.ForeignKey(AgentRun, on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name="external_usage")
    provider = models.CharField(max_length=30)  # "apify"
    purpose = models.CharField(max_length=50)  # "render_pages", "reddit_search"
    resource_id = models.CharField(max_length=200, blank=True)  # e.g. actor ID
    external_run_id = models.CharField(max_length=100, blank=True)
    items = models.PositiveIntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=12, decimal_places=6, default=0)
    error = models.TextField(blank=True)
    # For reading the run trail, not for billing: cost_usd stays the spend record apps/stats
    # aggregates. `status` is the provider's own word for how the call ended, kept even when
    # it succeeded, so "slow but fine" and "failed" are told apart without parsing `error`.
    status = models.CharField(max_length=30, blank=True)
    duration_ms = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.provider} {self.purpose} ${self.cost_usd}"
