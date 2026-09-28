from django.conf import settings
from django.db import models


class Project(models.Model):
    """A company's marketing workspace. Every domain row hangs off a project, and every
    project belongs to one user; a user may own several and switch between them.

    There is deliberately no `current()` helper. The project a request acts on depends on
    who is asking, so it is resolved per request in apps/core/selection.py. A global
    lookup that auto-created when the table was empty used to race: two processes both saw
    no rows and both created one, silently orphaning whatever landed on the loser.
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="projects"
    )
    name = models.CharField(max_length=120)
    website_url = models.URLField(blank=True)
    product_summary = models.TextField(blank=True)
    competitors = models.JSONField(default=list, blank=True)  # [{"name": str, "url": str}]
    onboarded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]
        indexes = [models.Index(fields=["owner", "id"])]

    def __str__(self):
        return self.name

    DEFAULT_NAME = "My project"


class WaitlistSignup(models.Model):
    """An email left on the public landing page. Not a user: accounts are still created by an admin."""

    email = models.EmailField(unique=True)
    source = models.CharField(max_length=40, blank=True)  # which form on the page, e.g. "hero"
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.email
