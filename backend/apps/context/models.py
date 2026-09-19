from django.db import models


class DocKind(models.TextChoices):
    # Declaration order is generation order and the order docs appear in every LLM call.
    PRODUCT = "product", "Product Information"
    AUDIENCE = "audience", "Target Audience"
    BRAND_VOICE = "brand_voice", "Brand Voice"
    COMPETITORS = "competitors", "Competitor Analysis"
    CONTENT_STRATEGY = "content_strategy", "Content Strategy"
    COMPLIANCE = "compliance", "Compliance Guidelines"


class DocSource(models.TextChoices):
    AI = "ai"
    HUMAN = "human"
    TEMPLATE = "template"


class CrawledPage(models.Model):
    project = models.ForeignKey("core.Project", on_delete=models.CASCADE, related_name="pages")
    url = models.URLField(max_length=1000)
    title = models.CharField(max_length=500, blank=True)
    content_text = models.TextField()
    content_hash = models.CharField(max_length=64)
    fetched_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]
        constraints = [models.UniqueConstraint(fields=["project", "url"], name="uniq_page_url")]

    def __str__(self):
        return self.url


class ContextDocument(models.Model):
    project = models.ForeignKey("core.Project", on_delete=models.CASCADE, related_name="documents")
    kind = models.CharField(max_length=30, choices=DocKind.choices)
    content_md = models.TextField(blank=True)
    source = models.CharField(max_length=20, choices=DocSource.choices, default=DocSource.AI)
    prompt_version = models.CharField(max_length=60, blank=True)
    model = models.CharField(max_length=100, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["project", "kind"], name="uniq_doc_kind")]

    def __str__(self):
        return self.title

    @property
    def title(self) -> str:
        return DocKind(self.kind).label


class ContextDocumentRevision(models.Model):
    """Every saved version of a document (AI, human edit, or template), newest last."""

    document = models.ForeignKey(ContextDocument, on_delete=models.CASCADE, related_name="revisions")
    content_md = models.TextField()
    source = models.CharField(max_length=20, choices=DocSource.choices)
    prompt_version = models.CharField(max_length=60, blank=True)
    model = models.CharField(max_length=100, blank=True)
    llm_call = models.ForeignKey("llm.LLMCall", on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.document.kind} rev {self.pk} ({self.source})"
