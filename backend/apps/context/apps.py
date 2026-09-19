from django.apps import AppConfig


class ContextConfig(AppConfig):
    name = "apps.context"
    label = "context"

    def ready(self):
        from llm.context import set_context_provider

        from .documents import context_documents_for_llm

        set_context_provider(context_documents_for_llm)
