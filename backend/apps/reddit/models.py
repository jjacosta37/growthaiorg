from django.db import models


class RedditPost(models.Model):
    """Every post the Reddit Agent has seen. Scored-but-undrafted posts are the "skipped" list,
    kept so the relevance threshold can be tuned."""

    class ScoreStatus(models.TextChoices):
        PENDING = "pending"  # waiting for scoring (possibly in a batch)
        SCORED = "scored"
        FAILED = "failed"

    project = models.ForeignKey("core.Project", on_delete=models.CASCADE, related_name="reddit_posts")
    reddit_id = models.CharField(max_length=20)
    subreddit = models.CharField(max_length=100)
    title = models.TextField()
    body = models.TextField(blank=True)
    url = models.URLField(max_length=1000)
    author = models.CharField(max_length=100, blank=True)
    upvotes = models.IntegerField(default=0)
    num_comments = models.IntegerField(default=0)
    flair = models.CharField(max_length=200, blank=True)
    posted_at = models.DateTimeField(null=True, blank=True)
    first_seen_run = models.ForeignKey("agents.AgentRun", on_delete=models.SET_NULL, null=True, blank=True,
                                       related_name="reddit_posts")
    fetched_at = models.DateTimeField(auto_now_add=True)

    score_status = models.CharField(max_length=20, choices=ScoreStatus.choices, default=ScoreStatus.PENDING)
    relevance_score = models.PositiveSmallIntegerField(null=True, blank=True, db_index=True)
    relevance_reason = models.TextField(blank=True)
    reply_worthwhile = models.BooleanField(null=True, blank=True)
    score_error = models.TextField(blank=True)
    scored_at = models.DateTimeField(null=True, blank=True)
    score_call = models.ForeignKey("llm.LLMCall", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        ordering = ["-fetched_at"]
        constraints = [models.UniqueConstraint(fields=["project", "reddit_id"], name="uniq_reddit_post")]

    def __str__(self):
        return f"r/{self.subreddit}: {self.title[:60]}"
