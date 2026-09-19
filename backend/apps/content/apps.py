from django.apps import AppConfig


class ContentConfig(AppConfig):
    name = "apps.content"
    label = "content"

    def ready(self):
        from . import agent  # noqa: F401  (registers the Content Agent)
