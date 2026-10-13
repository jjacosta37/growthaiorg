from django.db import models

LOW_VOLUME_THRESHOLD = 50  # monthly searches below which a topic is shown as "Low volume"


class BlogTopic(models.Model):
    """A proposed or requested blog topic. Proposed topics form a backlog the agent drafts from.

    A topic carries its evidence: the Reddit posts asking the question (`evidence_posts`) and
    search data for its candidate keywords, looked up once in the project's market. Search data
    is `pending` until a lookup succeeds, so a failed or deferred lookup is retried later.
    """

    class Status(models.TextChoices):
        PROPOSED = "proposed"
        DRAFTED = "drafted"
        REJECTED = "rejected"

    class SearchStatus(models.TextChoices):
        PENDING = "pending"
        READY = "ready"

    project = models.ForeignKey("core.Project", on_delete=models.CASCADE, related_name="blog_topics")
    title = models.CharField(max_length=300)
    angle = models.TextField(blank=True)
    target_keywords = models.JSONField(default=list, blank=True)
    pillar = models.CharField(max_length=200, blank=True)
    why = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PROPOSED, db_index=True)
    requested_by_user = models.BooleanField(default=False)
    evidence_posts = models.ManyToManyField("reddit.RedditPost", blank=True, related_name="blog_topics")
    search_status = models.CharField(max_length=20, choices=SearchStatus.choices, default=SearchStatus.PENDING)
    # [{"keyword", "volume", "difficulty"}] for every candidate looked up; difficulty may be null.
    keyword_metrics = models.JSONField(default=list, blank=True)
    primary_keyword = models.CharField(max_length=100, blank=True)
    search_volume = models.PositiveIntegerField(null=True, blank=True)
    keyword_difficulty = models.PositiveSmallIntegerField(null=True, blank=True)
    search_market = models.CharField(max_length=10, blank=True)  # "US/en": the market it was looked up in
    search_checked_at = models.DateTimeField(null=True, blank=True)
    created_run = models.ForeignKey("agents.AgentRun", on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="blog_topics")
    llm_call = models.ForeignKey("llm.LLMCall", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return self.title

    @property
    def low_volume(self) -> bool:
        """Looked up, and its primary keyword gets under `LOW_VOLUME_THRESHOLD` searches a month."""
        return self.search_status == self.SearchStatus.READY and (self.search_volume or 0) < LOW_VOLUME_THRESHOLD
