"""Agent pages: status header, config, run now, run history, and the Reddit skipped list."""

from django.db import transaction
from drf_spectacular.utils import OpenApiParameter, extend_schema
from pydantic import ValidationError as PydanticValidationError
from rest_framework import generics, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.models import Project

from . import registry
from .models import AgentConfig, AgentRun
from .runs import RunConflict, create_run
from .schedule import InvalidCron, next_run_at, parse_cron, sync_periodic_task
from .serializers import AgentRunSerializer
from .tasks import run_agent_task


def spec_or_404(agent_type: str):
    from django.http import Http404

    try:
        return registry.get(agent_type)
    except KeyError:
        raise Http404(f"Unknown agent {agent_type!r}") from None


def agent_config(project, spec) -> AgentConfig:
    config, created = AgentConfig.objects.get_or_create(
        project=project, agent_type=spec.agent_type, defaults={"cron": spec.default_cron}
    )
    return config


def agent_summary(project, spec) -> dict:
    from apps.inbox.models import Draft

    config = agent_config(project, spec)
    runs = AgentRun.objects.filter(project=project, kind=spec.agent_type)
    last = runs.first()
    last_finished = runs.exclude(finished_at=None).first()
    nxt = next_run_at(config)
    return {
        "agent_type": spec.agent_type,
        "label": spec.label,
        "enabled": config.enabled,
        "cron": config.cron,
        "config": spec.config_model.model_validate(config.config).model_dump(),
        "publish_mode": config.publish_mode,
        "last_run": AgentRunSerializer(last).data if last else None,
        "last_error": last_finished.error if last_finished and last_finished.status == "failed" else "",
        "next_run_at": nxt.isoformat() if nxt else None,
        "ready": Draft.objects.filter(project=project, agent_type=spec.agent_type, status=Draft.Status.NEW).count(),
    }


class AgentListView(APIView):
    @extend_schema(responses={200: dict})
    def get(self, request):
        project = Project.current()
        return Response([agent_summary(project, spec) for spec in registry.all_agents()])


class AgentConfigUpdateSerializer(serializers.Serializer):
    enabled = serializers.BooleanField(required=False)
    cron = serializers.CharField(required=False, max_length=100)
    config = serializers.JSONField(required=False)


class AgentDetailView(APIView):
    """GET the agent summary; PATCH {enabled?, cron?, config?} (config is merged, then validated)."""

    @extend_schema(responses={200: dict})
    def get(self, request, agent_type):
        return Response(agent_summary(Project.current(), spec_or_404(agent_type)))

    @extend_schema(request=AgentConfigUpdateSerializer, responses={200: dict})
    def patch(self, request, agent_type):
        spec = spec_or_404(agent_type)
        project = Project.current()
        data = AgentConfigUpdateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        config = agent_config(project, spec)
        v = data.validated_data
        if "cron" in v:
            try:
                parse_cron(v["cron"])
            except InvalidCron as exc:
                return Response({"cron": [str(exc)]}, status=status.HTTP_400_BAD_REQUEST)
            config.cron = v["cron"]
        if "config" in v:
            if not isinstance(v["config"], dict):
                return Response({"config": ["Must be an object"]}, status=status.HTTP_400_BAD_REQUEST)
            try:
                merged = spec.config_model.model_validate({**config.config, **v["config"]})
            except PydanticValidationError as exc:
                return Response({"config": exc.errors(include_url=False)}, status=status.HTTP_400_BAD_REQUEST)
            config.config = merged.model_dump()
        if "enabled" in v:
            config.enabled = v["enabled"]
        with transaction.atomic():
            config.save()
            sync_periodic_task(config)
        return Response(agent_summary(project, spec))


class RunNowView(APIView):
    @extend_schema(request=None, responses={202: AgentRunSerializer})
    def post(self, request, agent_type):
        spec = spec_or_404(agent_type)
        try:
            run = create_run(Project.current(), spec.agent_type, trigger=AgentRun.Trigger.MANUAL)
        except RunConflict as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        transaction.on_commit(lambda: run_agent_task.delay(run.id))
        return Response(AgentRunSerializer(run).data, status=status.HTTP_202_ACCEPTED)


class AgentRunsView(generics.ListAPIView):
    serializer_class = AgentRunSerializer

    def get_queryset(self):
        spec = spec_or_404(self.kwargs["agent_type"])
        return AgentRun.objects.filter(project=Project.current(), kind=spec.agent_type)


class SkippedPostSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    subreddit = serializers.CharField()
    title = serializers.CharField()
    url = serializers.URLField()
    upvotes = serializers.IntegerField()
    num_comments = serializers.IntegerField()
    posted_at = serializers.DateTimeField()
    score_status = serializers.CharField()
    relevance_score = serializers.IntegerField(allow_null=True)
    relevance_reason = serializers.CharField()
    reply_worthwhile = serializers.BooleanField(allow_null=True)
    score_error = serializers.CharField()
    fetched_at = serializers.DateTimeField()


class RedditSkippedView(generics.ListAPIView):
    """Posts scanned but not drafted, highest score first, for tuning the threshold.
    ?run=<id> limits to one run; ?min_score= filters."""

    serializer_class = SkippedPostSerializer

    @extend_schema(parameters=[OpenApiParameter("run", int), OpenApiParameter("min_score", int)])
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        from django.db.models import F

        from apps.reddit.models import RedditPost

        qs = RedditPost.objects.filter(project=Project.current(), drafts__isnull=True)
        if run_id := self.request.query_params.get("run"):
            qs = qs.filter(first_seen_run_id=run_id)
        if min_score := self.request.query_params.get("min_score"):
            qs = qs.filter(relevance_score__gte=int(min_score))
        return qs.order_by(F("relevance_score").desc(nulls_last=True), "-fetched_at")
