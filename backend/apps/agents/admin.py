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
    list_display = ("agent_type", "enabled", "schedule_summary", "publish_mode", "updated_at")

    @admin.display(description="Schedule")
    def schedule_summary(self, obj: AgentConfig) -> str:
        """The schedule in plain words, or the raw JSON if it can't be read."""
        from .schedule import InvalidSchedule, parse_schedule, summary

        try:
            return summary(parse_schedule(obj.schedule), obj.project.effective_timezone)
        except InvalidSchedule:
            return str(obj.schedule)


@admin.register(ExternalUsage)
class ExternalUsageAdmin(admin.ModelAdmin):
    list_display = ("created_at", "provider", "purpose", "items", "cost_usd", "error")
