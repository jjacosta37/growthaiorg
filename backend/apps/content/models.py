from django.db import models


class BlogTopic(models.Model):
    """A proposed or requested blog topic. Proposed topics form a backlog the agent drafts from."""

    class Status(models.TextChoices):
        PROPOSED = "proposed"
        DRAFTED = "drafted"
        REJECTED = "rejected"

    project = models.ForeignKey("core.Project", on_delete=models.CASCADE, related_name="blog_topics")
    title = models.CharField(max_length=300)
    angle = models.TextField(blank=True)
    target_keywords = models.JSONField(default=list, blank=True)
    pillar = models.CharField(max_length=200, blank=True)
    why = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PROPOSED, db_index=True)
    requested_by_user = models.BooleanField(default=False)
    created_run = models.ForeignKey("agents.AgentRun", on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="blog_topics")
    llm_call = models.ForeignKey("llm.LLMCall", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return self.title
