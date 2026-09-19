from django.db import models


class LLMBatch(models.Model):
    """One Message Batches API submission (used for non-urgent work like relevance scoring)."""

    class Status(models.TextChoices):
        SUBMITTED = "submitted"
        ENDED = "ended"  # Anthropic finished processing; results not yet collected
        COLLECTED = "collected"
        FAILED = "failed"

    project = models.ForeignKey("core.Project", on_delete=models.CASCADE, null=True, blank=True)
    agent_run = models.ForeignKey(
        "agents.AgentRun", on_delete=models.SET_NULL, null=True, blank=True, related_name="llm_batches"
    )
    anthropic_batch_id = models.CharField(max_length=100, unique=True)
    task = models.CharField(max_length=100)
    prompt_version = models.CharField(max_length=20)
    model = models.CharField(max_length=100)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SUBMITTED)
    request_count = models.PositiveIntegerField(default=0)
    succeeded_count = models.PositiveIntegerField(default=0)
    errored_count = models.PositiveIntegerField(default=0)
    meta = models.JSONField(default=dict, blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    collected_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.task} batch {self.anthropic_batch_id}"


class LLMCall(models.Model):
    """One model invocation, success or failure. Source of truth for in-app cost stats."""

    class Status(models.TextChoices):
        OK = "ok"
        ERROR = "error"
        REFUSED = "refused"
        TRUNCATED = "truncated"
        INVALID_OUTPUT = "invalid_output"

    project = models.ForeignKey("core.Project", on_delete=models.SET_NULL, null=True, blank=True)
    agent_run = models.ForeignKey(
        "agents.AgentRun", on_delete=models.SET_NULL, null=True, blank=True, related_name="llm_calls"
    )
    task = models.CharField(max_length=100, db_index=True)
    model = models.CharField(max_length=100)
    prompt_version = models.CharField(max_length=20)
    prompt_hash = models.CharField(max_length=16)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OK)
    error = models.TextField(blank=True)
    stop_reason = models.CharField(max_length=30, blank=True)

    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    cache_read_tokens = models.PositiveIntegerField(default=0)
    cache_write_tokens = models.PositiveIntegerField(default=0)
    web_search_requests = models.PositiveIntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=12, decimal_places=6, default=0)
    latency_ms = models.PositiveIntegerField(default=0)

    is_batch = models.BooleanField(default=False)
    batch = models.ForeignKey(LLMBatch, on_delete=models.SET_NULL, null=True, blank=True, related_name="calls")
    custom_id = models.CharField(max_length=64, blank=True)
    request_id = models.CharField(max_length=100, blank=True)
    langsmith_run_id = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.task} {self.model} {self.status}"
