from django.apps import AppConfig


class PublishingConfig(AppConfig):
    """Opening blog drafts as pull requests in a project's connected repository."""

    name = "apps.publishing"
    label = "publishing"
