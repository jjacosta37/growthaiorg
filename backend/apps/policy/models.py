from django.db import models

DEFAULT_PACK = "general"
DEFAULT_DISCLOSURE = "(Disclosure: I'm the {role} of {project}.)"


class ContentPolicy(models.Model):
    """What a project's drafts must never do, plus how affiliation is disclosed. Seeded from a policy
    pack (policies/*.yaml) and then freely editable. Rendered into every LLM call's guardrails and used
    by the compliance lint, so all agents follow the same rules."""

    class Source(models.TextChoices):
        DEFAULT = "default"  # never chosen; onboarding may replace it with a suggestion
        SUGGESTED = "suggested"  # picked by onboarding from the website
        USER = "user"  # chosen or edited by the user; never overwritten automatically

    project = models.OneToOneField("core.Project", on_delete=models.CASCADE, related_name="content_policy")
    pack = models.CharField(max_length=50, default=DEFAULT_PACK)
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.DEFAULT)
    author_role = models.CharField(max_length=60, default="founder",
                                   help_text="Who posts the drafts, e.g. founder, CEO, marketing lead")
    rules = models.JSONField(default=list)  # [{id, title, description}]
    disclosure = models.CharField(max_length=300, default=DEFAULT_DISCLOSURE,
                                  help_text="Affiliation disclosure; {role} and {project} are filled in")
    blog_disclaimer = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.project} policy ({self.pack})"

    def rendered_disclosure(self) -> str:
        return self.disclosure.replace("{role}", self.author_role).replace("{project}", self.project.name)
