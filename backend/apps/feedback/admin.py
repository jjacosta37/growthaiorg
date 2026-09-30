from django.contrib import admin

from .models import AgentFeedback, AgentLearnings


@admin.register(AgentFeedback)
class AgentFeedbackAdmin(admin.ModelAdmin):
    list_display = ("id", "project", "agent_type", "source", "rating", "created_at", "digested_at")
    list_filter = ("agent_type", "source", "rating")


@admin.register(AgentLearnings)
class AgentLearningsAdmin(admin.ModelAdmin):
    list_display = ("project", "agent_type", "source", "updated_at")
