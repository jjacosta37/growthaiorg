from rest_framework import serializers

from .models import AgentRun, RunEvent


class RunEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = RunEvent
        fields = ["id", "level", "message", "data", "created_at"]


class AgentRunSerializer(serializers.ModelSerializer):
    class Meta:
        model = AgentRun
        fields = ["id", "kind", "trigger", "status", "current_step", "params", "stats", "error",
                  "created_at", "started_at", "finished_at"]
