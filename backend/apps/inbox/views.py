from django.db import transaction
from django.db.models import Count, F, QuerySet
from drf_spectacular.utils import OpenApiParameter, extend_schema
from pydantic import ValidationError as PydanticValidationError
from rest_framework import generics, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.agents.models import AgentRun
from apps.agents.serializers import AgentRunSerializer
from apps.agents.tasks import regenerate_draft_task
from apps.core.errors import validation_errors
from apps.core.selection import current_project
from apps.feedback import services as feedback
from apps.feedback.models import AgentFeedback

from . import services
from .models import Draft
from .serializers import (
    DismissSerializer,
    DraftDetailSerializer,
    DraftListSerializer,
    EditSerializer,
    MarkPostedSerializer,
    RegenerateSerializer,
)


def drafts_qs(request):
    """Drafts belonging to the caller's current project.

    Every draft endpoint looks its object up through here, so scoping this one function is
    what keeps one user's inbox out of another's.
    """
    return (Draft.objects.filter(project=current_project(request))
            .select_related("current_version", "source_reddit_post", "blog_topic", "project"))


class DraftListView(generics.ListAPIView):
    """Inbox list. Filters: ?agent=reddit,x ?status=new|posted|dismissed ?sort=newest|score"""

    serializer_class = DraftListSerializer

    @extend_schema(parameters=[OpenApiParameter("agent", str), OpenApiParameter("status", str),
                               OpenApiParameter("sort", str, enum=["newest", "score"])])
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        qs = drafts_qs(self.request)
        params = self.request.query_params
        if agent := params.get("agent"):
            qs = qs.filter(agent_type__in=agent.split(","))
        qs = qs.filter(status=params.get("status") or Draft.Status.NEW)
        if params.get("sort") == "score":
            return qs.order_by(F("source_reddit_post__relevance_score").desc(nulls_last=True), "-created_at")
        return qs.order_by("-created_at")


class DraftDetailView(generics.RetrieveAPIView):
    """GET one draft with its versions and feedback."""

    serializer_class = DraftDetailSerializer

    def get_queryset(self) -> QuerySet[Draft]:
        """The caller's drafts, with what the detail pane renders prefetched."""
        return drafts_qs(self.request).prefetch_related("versions", "feedback")


class _DraftAction(APIView):
    """Base for the draft action views: scoped lookup, and the detail response they return."""

    def get_draft(self, request, pk) -> Draft:
        return generics.get_object_or_404(drafts_qs(request), pk=pk)

    def detail(self, request: Request, draft: Draft) -> Response:
        """The draft re-read with its versions and feedback, as the detail pane shows it."""
        draft = drafts_qs(request).prefetch_related("versions", "feedback").get(pk=draft.pk)
        return Response(DraftDetailSerializer(draft).data)


class EditView(_DraftAction):
    @extend_schema(request=EditSerializer, responses={200: DraftDetailSerializer})
    def post(self, request, pk):
        data = EditSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        draft = self.get_draft(request, pk)
        try:
            services.edit(draft, data.validated_data["content"])
        except services.DraftStateError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        except PydanticValidationError as exc:
            return Response({"content": validation_errors(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return self.detail(request, draft)


class RegenerateView(_DraftAction):
    """POST {nudge?, instruction?, remember?}: regenerate a draft in the background."""

    @extend_schema(request=RegenerateSerializer, responses={202: AgentRunSerializer})
    def post(self, request: Request, pk: int) -> Response:
        """Start the regeneration, or 409 if the draft isn't new or is already regenerating.

        With `remember`, the instruction is also stored as feedback for future drafts, but only
        once the request has passed the 409 checks.
        """
        data = RegenerateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        draft = self.get_draft(request, pk)
        if draft.status != Draft.Status.NEW:
            return Response({"detail": f"Can't regenerate a draft that is {draft.status}"},
                            status=status.HTTP_409_CONFLICT)
        # One regeneration per draft at a time; different drafts can regenerate in parallel.
        if AgentRun.objects.filter(kind=AgentRun.Kind.REGENERATE_DRAFT, status__in=AgentRun.ACTIVE,
                                   params__draft_id=draft.pk).exists():
            return Response({"detail": "This draft is already regenerating"}, status=status.HTTP_409_CONFLICT)
        params = dict(data.validated_data)
        if params.pop("remember"):
            feedback.record(draft, source=AgentFeedback.Source.INSTRUCTION, text=params["instruction"])
        run = AgentRun.objects.create(project=draft.project, kind=AgentRun.Kind.REGENERATE_DRAFT,
                                      params={"draft_id": draft.pk, **params})
        transaction.on_commit(lambda: regenerate_draft_task.delay(run.id))
        return Response(AgentRunSerializer(run).data, status=status.HTTP_202_ACCEPTED)


class MarkPostedView(_DraftAction):
    @extend_schema(request=MarkPostedSerializer, responses={200: DraftDetailSerializer})
    def post(self, request, pk):
        data = MarkPostedSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        draft = self.get_draft(request, pk)
        services.mark_posted(draft, data.validated_data["posted_url"])
        return self.detail(request, draft)


class DismissView(_DraftAction):
    @extend_schema(request=DismissSerializer, responses={200: DraftDetailSerializer})
    def post(self, request, pk):
        data = DismissSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        draft = self.get_draft(request, pk)
        try:
            services.dismiss(draft, data.validated_data["reason"], data.validated_data["note"])
        except services.DraftStateError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        return self.detail(request, draft)


class RestoreView(_DraftAction):
    @extend_schema(request=None, responses={200: DraftDetailSerializer})
    def post(self, request, pk):
        draft = self.get_draft(request, pk)
        services.restore(draft)
        return self.detail(request, draft)


class ReadView(_DraftAction):
    @extend_schema(request=None, responses={204: None})
    def post(self, request, pk):
        services.mark_read(self.get_draft(request, pk))
        return Response(status=status.HTTP_204_NO_CONTENT)


class InboxCountsView(APIView):
    """Sidebar badges: unread in the inbox, and drafts ready (new) per agent."""

    @extend_schema(responses={200: dict})
    def get(self, request):
        new = Draft.objects.filter(project=current_project(request), status=Draft.Status.NEW)
        per_agent = dict(new.values_list("agent_type").annotate(n=Count("id")).values_list("agent_type", "n"))
        return Response({
            "unread": new.filter(read_at__isnull=True).count(),
            "ready": {a: per_agent.get(a, 0) for a in ("reddit", "content", "x")},
            "total_new": new.count(),
            "flagged": new.exclude(compliance_flags=[]).count(),
        })

