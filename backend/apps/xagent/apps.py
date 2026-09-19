from django.apps import AppConfig


class XAgentAppConfig(AppConfig):
    name = "apps.xagent"
    label = "xagent"

    def ready(self):
        from . import agent  # noqa: F401  (registers the X Agent)
