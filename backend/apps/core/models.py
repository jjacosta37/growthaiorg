from django.db import models


class Project(models.Model):
    """The product Sift is growing. Single-user today; every domain row hangs off a project."""

    name = models.CharField(max_length=120)
    website_url = models.URLField(blank=True)
    product_summary = models.TextField(blank=True)
    competitors = models.JSONField(default=list, blank=True)  # [{"name": str, "url": str}]
    onboarded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return self.name

    DEFAULT_NAME = "My project"

    @classmethod
    def current(cls) -> "Project":
        """The single project for now. Every query already filters by project, so multi-project
        support only needs this lookup to change."""
        project = cls.objects.first()
        if project is None:
            project = cls.objects.create(name=cls.DEFAULT_NAME)
        return project
