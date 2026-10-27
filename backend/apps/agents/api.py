"""Agent pages: status header, config, run now, run history, and the Reddit skipped list."""

from django.db import transaction
from drf_spectacular.utils import OpenApiParameter, extend_schema
from pydantic import ValidationError as PydanticValidationError
from rest_framework import generics, serializers, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.errors import validation_errors
from apps.core.models import Project
from apps.core.selection import current_project
from apps.core.text import http_url

from . import registry
from .draft_models import available_draft_models, draft_model_options, effective_draft_key
from .models import AgentConfig, AgentRun, AgentType
from .runs import RunConflict, create_run
from .schedule import (
    InvalidSchedule,
    min_gap,
    next_run_at,
    next_runs,
    parse_schedule,
    summary,
    sync_periodic_task,
    sync_project_tasks,
    too_frequent,
    valid_timezone,
    writable_schedule,
)
from .serializers import AgentRunSerializer
from .tasks import run_agent_task


def spec_or_404(agent_type: str):
    from django.http import Http404

    try:
        return registry.get(agent_type)
    except KeyError:
        raise Http404(f"Unknown agent {agent_type!r}") from None


def agent_config(project, spec) -> AgentConfig:
    return AgentConfig.for_project(project, spec.agent_type)


def agent_summary(project: Project, spec: registry.AgentSpec) -> dict:
    """The agent page header: schedule, config, drafting model and its options, last/next run, ready count."""
    from apps.inbox.models import Draft

    config = agent_config(project, spec)
    runs = AgentRun.objects.filter(project=project, kind=spec.agent_type)
    last = runs.first()
    last_finished = runs.exclude(finished_at=None).first()
    nxt = next_run_at(config)
    return {
        **schedule_summary(project, config),
        "agent_type": spec.agent_type,
        "label": spec.label,
        "enabled": config.enabled,
        "config": spec.config_model.model_validate(config.config).model_dump(),
        "publish_mode": config.publish_mode,
        "automatic_available": _automatic_available(project, spec),
        "draft_model": effective_draft_key(project, config.draft_model),
        "draft_models": draft_model_options(project),
        "last_run": AgentRunSerializer(last).data if last else None,
        "last_error": last_finished.error if last_finished and last_finished.status == "failed" else "",
        "next_run_at": nxt.isoformat() if nxt else None,
        "ready": Draft.objects.filter(project=project, agent_type=spec.agent_type, status=Draft.Status.NEW).count(),
        "repeat_hint": repeat_hint(project, config) if spec.agent_type == AgentType.REDDIT else None,
    }


TIME_WINDOW_HOURS = {"hour": 1, "day": 24, "week": 168}


def repeat_hint(project: Project, config: AgentConfig) -> dict | None:
    """Flag a Reddit time window more than twice the gap between scheduled runs.

    Each run then searches mostly the same stretch of time as the one before, so most results are
    posts already seen, whatever the subreddits and keywords. Only for an enabled (scheduled) agent.

    Returns:
        `{time_window, window_hours, gap_hours}`, or None when there's nothing to flag.
    """
    if not config.enabled:
        return None
    window = config.config.get("time_window", "day")
    window_hours = TIME_WINDOW_HOURS.get(window)
    gap = min_gap(parse_schedule(config.schedule), project.effective_timezone)
    if window_hours is None or gap is None:
        return None
    gap_hours = gap.total_seconds() / 3600
    if window_hours <= 2 * gap_hours:
        return None
    return {"time_window": window, "window_hours": window_hours, "gap_hours": round(gap_hours, 1)}


def schedule_summary(project: Project, config: AgentConfig) -> dict:
    """The schedule fields of the agent summary.

    `too_frequent` flags a schedule saved before the hourly minimum; it keeps running until replaced.
    """
    tz = project.effective_timezone
    schedule = parse_schedule(config.schedule)
    return {
        "schedule": schedule.model_dump(),
        "schedule_summary": summary(schedule, tz),
        "next_runs": [t.isoformat() for t in next_runs(schedule, tz)],
        "schedule_warning": "too_frequent" if too_frequent(schedule, tz) else None,
        "timezone": tz,
        "timezone_set": bool(project.timezone),
    }


def _automatic_available(project: Project, spec: registry.AgentSpec) -> bool:
    """Automatic mode is the Content Agent's, and needs a ready GitHub connection."""
    from apps.publishing.connections import can_automate

    return spec.agent_type == AgentType.CONTENT and can_automate(project)


class AgentListView(APIView):
    @extend_schema(operation_id="agents_list", responses={200: dict})
    def get(self, request):
        project = current_project(request)
        return Response([agent_summary(project, spec) for spec in registry.all_agents()])


class AgentConfigUpdateSerializer(serializers.Serializer):
    enabled = serializers.BooleanField(required=False)
    schedule = serializers.JSONField(required=False)
    timezone = serializers.CharField(required=False, max_length=64)
    config = serializers.JSONField(required=False)
    draft_model = serializers.CharField(required=False, max_length=20)
    publish_mode = serializers.ChoiceField(choices=AgentConfig.PublishMode.choices, required=False)


class AgentDetailView(APIView):
    """GET the agent summary; PATCH {enabled?, schedule?, timezone?, config?, draft_model?, publish_mode?}
    (config is merged, then validated; timezone is the project's and applies to all its agents)."""

    @extend_schema(responses={200: dict})
    def get(self, request, agent_type):
        return Response(agent_summary(current_project(request), spec_or_404(agent_type)))

    @extend_schema(request=AgentConfigUpdateSerializer, responses={200: dict})
    def patch(self, request: Request, agent_type: str) -> Response:
        """PATCH the agent's settings; draft_model must be a key this project may use."""
        spec = spec_or_404(agent_type)
        project = current_project(request)
        data = AgentConfigUpdateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        config = agent_config(project, spec)
        v = data.validated_data
        if "schedule" in v:
            try:
                config.schedule = writable_schedule(v["schedule"]).model_dump()
            except InvalidSchedule as exc:
                return Response({"schedule": [str(exc)]}, status=status.HTTP_400_BAD_REQUEST)
        if "timezone" in v:
            try:
                project.timezone = valid_timezone(v["timezone"])
            except InvalidSchedule as exc:
                return Response({"timezone": [str(exc)]}, status=status.HTTP_400_BAD_REQUEST)
        if "config" in v:
            if not isinstance(v["config"], dict):
                return Response({"config": ["Must be an object"]}, status=status.HTTP_400_BAD_REQUEST)
            try:
                merged = spec.config_model.model_validate({**config.config, **v["config"]})
            except PydanticValidationError as exc:
                return Response({"config": validation_errors(exc)}, status=status.HTTP_400_BAD_REQUEST)
            config.config = merged.model_dump()
        if "draft_model" in v:
            if v["draft_model"] not in available_draft_models(project):
                return Response({"draft_model": ["Not an available model"]}, status=status.HTTP_400_BAD_REQUEST)
            config.draft_model = v["draft_model"]
        if "publish_mode" in v:
            if v["publish_mode"] == AgentConfig.PublishMode.AUTOMATIC and not _automatic_available(project, spec):
                return Response({"publish_mode": ["Automatic pull requests need a connected GitHub repository"]},
                                status=status.HTTP_400_BAD_REQUEST)
            config.publish_mode = v["publish_mode"]
        if "enabled" in v:
            config.enabled = v["enabled"]
        with transaction.atomic():
            config.save()
            if "timezone" in v:
                project.save(update_fields=["timezone", "updated_at"])
                sync_project_tasks(project)  # local times stay; every agent now runs in the new zone
            else:
                sync_periodic_task(config)
        return Response(agent_summary(project, spec))


class SchedulePreviewSerializer(serializers.Serializer):
    schedule = serializers.JSONField()
    timezone = serializers.CharField(required=False, max_length=64)


class SchedulePreviewView(APIView):
    """POST {schedule, timezone?}: the summary and next 3 runs of an unsaved schedule. Writes nothing."""

    @extend_schema(request=SchedulePreviewSerializer, responses={200: dict})
    def post(self, request: Request) -> Response:
        """Validate like a save would, then describe it (timezone defaults to the project's)."""
        project = current_project(request)
        data = SchedulePreviewSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        try:
            tz = valid_timezone(v["timezone"]) if "timezone" in v else project.effective_timezone
        except InvalidSchedule as exc:
            return Response({"timezone": [str(exc)]}, status=status.HTTP_400_BAD_REQUEST)
        try:
            schedule = writable_schedule(v["schedule"])
        except InvalidSchedule as exc:
            return Response({"schedule": [str(exc)]}, status=status.HTTP_400_BAD_REQUEST)
        return Response({
            "summary": summary(schedule, tz),
            "next_runs": [t.isoformat() for t in next_runs(schedule, tz)],
        })


class RunNowView(APIView):
    @extend_schema(request=None, responses={202: AgentRunSerializer})
    def post(self, request, agent_type):
        spec = spec_or_404(agent_type)
        try:
            run = create_run(current_project(request), spec.agent_type, trigger=AgentRun.Trigger.MANUAL)
        except RunConflict as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        transaction.on_commit(lambda: run_agent_task.delay(run.id))
        return Response(AgentRunSerializer(run).data, status=status.HTTP_202_ACCEPTED)


class AgentRunsView(generics.ListAPIView):
    serializer_class = AgentRunSerializer

    def get_queryset(self):
        spec = spec_or_404(self.kwargs["agent_type"])
        return AgentRun.objects.filter(project=current_project(self.request), kind=spec.agent_type)


class SkippedPostSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    subreddit = serializers.CharField()
    title = serializers.CharField()
    url = serializers.SerializerMethodField()
    upvotes = serializers.IntegerField()
    num_comments = serializers.IntegerField()
    posted_at = serializers.DateTimeField()
    score_status = serializers.CharField()
    relevance_score = serializers.IntegerField(allow_null=True)
    relevance_reason = serializers.CharField()
    reply_worthwhile = serializers.BooleanField(allow_null=True)
    score_error = serializers.CharField()
    fetched_at = serializers.DateTimeField()


    def get_url(self, obj) -> str:
        """The post's link, or "" if it isn't http(s)."""
        return http_url(obj.url)


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

        qs = RedditPost.objects.filter(project=current_project(self.request), drafts__isnull=True)
        if run_id := self.request.query_params.get("run"):
            qs = qs.filter(first_seen_run_id=run_id)
        if min_score := self.request.query_params.get("min_score"):
            qs = qs.filter(relevance_score__gte=int(min_score))
        return qs.order_by(F("relevance_score").desc(nulls_last=True), "-fetched_at")


# --- Reddit "Suggest more" (docs/prds/0004-reddit-target-suggestions.md) -------------------


def suggestions_payload(project: Project) -> dict:
    """What the suggestions card shows: pending suggestions, room left, and the latest run's state.

    `nothing_new` is true when the latest "Suggest more" succeeded but had nothing new to offer.
    `last_error` is set when it failed, so the card can offer a retry.
    """
    from apps.reddit.config import MAX_KEYWORDS, MAX_SUBREDDITS
    from apps.reddit.models import RedditTargetSuggestion
    from apps.reddit.suggestions import pending_suggestions, reddit_config

    _, cfg = reddit_config(project)
    pending = pending_suggestions(project, cfg)
    last = AgentRun.objects.filter(project=project, kind=AgentRun.Kind.SUGGEST_REDDIT_TARGETS).first()

    def rows(kind: str) -> list[dict]:
        return [{"id": r.id, "value": r.value, "reason": r.reason} for r in pending if r.kind == kind]

    return {
        "suggesting": bool(last and last.is_active),
        "last_error": last.error.split("\n", 1)[0][:300] if last and last.status == AgentRun.Status.FAILED else "",
        "nothing_new": bool(last and last.status == AgentRun.Status.SUCCEEDED and not pending
                            and last.stats.get("suggested") == 0),
        "subreddits": rows(RedditTargetSuggestion.Kind.SUBREDDIT),
        "keywords": rows(RedditTargetSuggestion.Kind.KEYWORD),
        "room": {"subreddits": max(0, MAX_SUBREDDITS - len(cfg.subreddits)),
                 "keywords": max(0, MAX_KEYWORDS - len(cfg.keywords))},
        "limits": {"subreddits": MAX_SUBREDDITS, "keywords": MAX_KEYWORDS},
    }


class RedditSuggestionsView(APIView):
    """GET the pending subreddit and keyword suggestions; POST starts "Suggest more" (409 while one runs)."""

    @extend_schema(responses={200: dict})
    def get(self, request: Request) -> Response:
        """Return the suggestions card's state."""
        return Response(suggestions_payload(current_project(request)))

    @extend_schema(request=None, responses={202: dict})
    def post(self, request: Request) -> Response:
        """Queue one suggestion run for the caller's project."""
        from apps.reddit.tasks import suggest_targets_task

        project = current_project(request)
        try:
            run = create_run(project, AgentRun.Kind.SUGGEST_REDDIT_TARGETS)
        except RunConflict:
            return Response({"detail": "Already suggesting; results will appear shortly."},
                            status=status.HTTP_409_CONFLICT)
        transaction.on_commit(lambda: suggest_targets_task.delay(run.id))
        return Response(suggestions_payload(project), status=status.HTTP_202_ACCEPTED)


class AddSuggestionsSerializer(serializers.Serializer):
    ids = serializers.ListField(child=serializers.IntegerField(min_value=1), min_length=1, max_length=100)


class RedditSuggestionsAddView(APIView):
    """POST {ids}: append the chosen suggestions to the Reddit Agent's config."""

    @extend_schema(request=AddSuggestionsSerializer, responses={200: dict})
    def post(self, request: Request) -> Response:
        """Add the suggestions, or 400 with the reason if a config limit would be exceeded."""
        from apps.reddit.suggestions import SuggestionLimit, add_suggestions

        project = current_project(request)
        data = AddSuggestionsSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            added = add_suggestions(project, data.validated_data["ids"])
        except SuggestionLimit as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({**suggestions_payload(project), "added": added})


class RedditSuggestionDismissView(APIView):
    """POST: dismiss one pending suggestion, so it's never suggested again for this project."""

    @extend_schema(request=None, responses={200: dict})
    def post(self, request: Request, pk: int) -> Response:
        """Mark the suggestion dismissed; 404 unless it's a pending suggestion of the caller's project."""
        from django.utils import timezone

        from apps.reddit.models import RedditTargetSuggestion

        project = current_project(request)
        updated = RedditTargetSuggestion.objects.filter(
            pk=pk, project=project, status=RedditTargetSuggestion.Status.PENDING,
        ).update(status=RedditTargetSuggestion.Status.DISMISSED, decided_at=timezone.now())
        if not updated:
            from django.http import Http404

            raise Http404("No such suggestion")
        return Response(suggestions_payload(project))
