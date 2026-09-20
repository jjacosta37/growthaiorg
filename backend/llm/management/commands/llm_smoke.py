"""Real API round-trip: checks the key, model names, structured output, cost logging and tracing."""

from django.conf import settings
from django.core.management.base import BaseCommand

import llm


class Command(BaseCommand):
    help = "Call the fast model once through llm.complete() and print the logged LLMCall."

    def handle(self, *args, **options):
        result = llm.complete("smoke", {"word": "helm"})
        call = result.call
        self.stdout.write(self.style.SUCCESS(f"parsed={result.parsed!r}"))
        self.stdout.write(
            f"model={call.model} tokens in/out={call.input_tokens}/{call.output_tokens} "
            f"cost=${call.cost_usd} latency={call.latency_ms}ms request_id={call.request_id}"
        )
        self.stdout.write(f"langsmith tracing={'on' if settings.LANGSMITH_TRACING else 'off'}")
