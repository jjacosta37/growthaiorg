from django.contrib import admin

from .models import AgentConfig, AgentRun, ExternalUsage, RunEvent


class RunEventInline(admin.TabularInline):
    model = RunEvent
    extra = 0
    readonly_fields = ("created_at", "level", "message", "data")


@admin.register(AgentRun)
class AgentRunAdmin(admin.ModelAdmin):
    list_display = ("id", "kind", "trigger", "status", "current_step", "created_at", "finished_at")
    list_filter = ("kind", "status")
    inlines = [RunEventInline]


@admin.register(AgentConfig)
class AgentConfigAdmin(admin.ModelAdmin):
    list_display = ("agent_type", "enabled", "cron", "publish_mode", "updated_at")


@admin.register(ExternalUsage)
class ExternalUsageAdmin(admin.ModelAdmin):
    list_display = ("created_at", "provider", "purpose", "items", "cost_usd", "error")
