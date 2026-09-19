from django.apps import AppConfig


class RedditConfig(AppConfig):
    name = "apps.reddit"
    label = "reddit"

    def ready(self):
        from . import agent  # noqa: F401  (registers the Reddit Agent)
