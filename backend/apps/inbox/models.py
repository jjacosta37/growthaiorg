from django.db import models


class DraftKind(models.TextChoices):
    REDDIT_COMMENT = "reddit_comment"
    X_POST = "x_post"
    X_THREAD = "x_thread"
    BLOG_POST = "blog_post"


class Draft(models.Model):
    """An item in the inbox. The content lives in versions; `current_version` is what's shown."""

    class Status(models.TextChoices):
        NEW = "new"
        POSTED = "posted"
        DISMISSED = "dismissed"

    class DismissReason(models.TextChoices):
        NOT_RELEVANT = "not_relevant"
        ALREADY_ANSWERED = "already_answered"
        TOO_PROMOTIONAL = "too_promotional"
        OTHER = "other"

    project = models.ForeignKey("core.Project", on_delete=models.CASCADE, related_name="drafts")
    agent_type = models.CharField(max_length=20)  # AgentType value
    kind = models.CharField(max_length=20, choices=DraftKind.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW, db_index=True)
    agent_run = models.ForeignKey("agents.AgentRun", on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name="drafts")
    source_reddit_post = models.ForeignKey("reddit.RedditPost", on_delete=models.SET_NULL, null=True, blank=True,
                                           related_name="drafts")
    blog_topic = models.ForeignKey("content.BlogTopic", on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="drafts")
    current_version = models.ForeignKey("DraftVersion", on_delete=models.SET_NULL, null=True, blank=True,
                                        related_name="+")
    compliance_flags = models.JSONField(default=list, blank=True)  # [{rule, excerpt, explanation}]
    read_at = models.DateTimeField(null=True, blank=True)
    posted_at = models.DateTimeField(null=True, blank=True)
    posted_url = models.URLField(max_length=1000, blank=True)
    dismiss_reason = models.CharField(max_length=30, choices=DismissReason.choices, blank=True)
    dismiss_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["project", "status", "-created_at"])]

    def __str__(self):
        return f"{self.kind} #{self.pk} {self.status}"


class DraftVersion(models.Model):
    """Every version of a draft. Together with dismiss reasons, this is the prompt-evaluation
    dataset: the last AI version vs. what I edited and posted."""

    class Source(models.TextChoices):
        AI_INITIAL = "ai_initial"
        AI_REGENERATED = "ai_regenerated"
        HUMAN_EDIT = "human_edit"

    draft = models.ForeignKey(Draft, on_delete=models.CASCADE, related_name="versions")
    n = models.PositiveIntegerField()
    source = models.CharField(max_length=20, choices=Source.choices)
    content = models.JSONField()
    nudge = models.CharField(max_length=30, blank=True)
    instruction = models.TextField(blank=True)
    prompt_name = models.CharField(max_length=100, blank=True)
    prompt_version = models.CharField(max_length=20, blank=True)
    model = models.CharField(max_length=100, blank=True)
    llm_call = models.ForeignKey("llm.LLMCall", on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["n"]
        constraints = [models.UniqueConstraint(fields=["draft", "n"], name="uniq_draft_version_n")]

    def __str__(self):
        return f"draft {self.draft_id} v{self.n} ({self.source})"

    @property
    def is_ai(self) -> bool:
        return self.source != self.Source.HUMAN_EDIT
