from django.apps import AppConfig


class PolicyConfig(AppConfig):
    name = "apps.policy"
    label = "policy"

    def ready(self):
        from llm.context import set_policy_provider

        from .service import guardrail_variables

        set_policy_provider(guardrail_variables)
