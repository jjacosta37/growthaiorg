from django.contrib import admin

from .models import Draft, DraftVersion


class DraftVersionInline(admin.TabularInline):
    model = DraftVersion
    fk_name = "draft"
    extra = 0
    readonly_fields = ("n", "source", "nudge", "instruction", "prompt_version", "model", "created_at")


@admin.register(Draft)
class DraftAdmin(admin.ModelAdmin):
    list_display = ("id", "project", "agent_type", "kind", "status", "created_at", "posted_at")
    list_filter = ("project", "agent_type", "kind", "status")
    inlines = [DraftVersionInline]
