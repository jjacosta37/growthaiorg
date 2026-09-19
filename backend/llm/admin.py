from django.contrib import admin

from .models import LLMBatch, LLMCall


@admin.register(LLMCall)
class LLMCallAdmin(admin.ModelAdmin):
    list_display = ("created_at", "task", "model", "prompt_version", "status", "input_tokens",
                    "output_tokens", "cache_read_tokens", "cost_usd", "latency_ms", "is_batch")
    list_filter = ("task", "model", "status", "is_batch")


@admin.register(LLMBatch)
class LLMBatchAdmin(admin.ModelAdmin):
    list_display = ("submitted_at", "task", "status", "request_count", "succeeded_count", "errored_count")
    list_filter = ("task", "status")
