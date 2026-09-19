from django.apps import AppConfig


class AgentsConfig(AppConfig):
    name = "apps.agents"
    label = "agents"

    def ready(self):
        from apps.core.status import register_status_contributor

        from .status import active_runs_status

        register_status_contributor(active_runs_status)
