from django.db import models


class AgentFeedback(models.Model):
    """One piece of feedback the user gave an agent about its drafts. Kept raw; the digest in
    AgentLearnings is what prompts read, plus any entries it hasn't absorbed yet."""

    class Source(models.TextChoices):
        EXPLICIT = "explicit"  # the feedback box on a draft
        INSTRUCTION = "instruction"  # a regenerate instruction with "remember for future" ticked

    class Rating(models.TextChoices):
        UP = "up"
        DOWN = "down"

    project = models.ForeignKey("core.Project", on_delete=models.CASCADE, related_name="agent_feedback")
    agent_type = models.CharField(max_length=20)  # AgentType value
    draft = models.ForeignKey("inbox.Draft", on_delete=models.SET_NULL, null=True, blank=True,
                              related_name="feedback")
    draft_version = models.ForeignKey("inbox.DraftVersion", on_delete=models.SET_NULL, null=True, blank=True,
                                      related_name="+")
    source = models.CharField(max_length=20, choices=Source.choices)
    rating = models.CharField(max_length=10, choices=Rating.choices, blank=True)
    text = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    digested_at = models.DateTimeField(null=True, blank=True)  # null: not yet folded into the digest

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["project", "agent_type", "digested_at"])]

    def __str__(self):
        return f"{self.agent_type} feedback #{self.pk} ({self.source})"


class AgentLearnings(models.Model):
    """What an agent has learned from feedback: a short digest, maintained by an LLM and editable
    by the user. `writing_md` steers drafting; `selection_md` steers which items get a draft."""

    class Source(models.TextChoices):
        AI = "ai"
        HUMAN = "human"

    project = models.ForeignKey("core.Project", on_delete=models.CASCADE, related_name="agent_learnings")
    agent_type = models.CharField(max_length=20)
    writing_md = models.TextField(blank=True)
    selection_md = models.TextField(blank=True)
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.AI)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["project", "agent_type"], name="uniq_learnings_per_agent")]

    def __str__(self):
        return f"{self.project} {self.agent_type} learnings"

    @classmethod
    def for_project(cls, project, agent_type: str) -> "AgentLearnings":
        obj, _ = cls.objects.get_or_create(project=project, agent_type=agent_type)
        return obj
