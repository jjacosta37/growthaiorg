from django.db import transaction
from django.db.models import Count, F
from drf_spectacular.utils import OpenApiParameter, extend_schema
from pydantic import ValidationError as PydanticValidationError
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.agents.models import AgentRun
from apps.agents.serializers import AgentRunSerializer
from apps.agents.tasks import regenerate_draft_task
from apps.core.models import Project

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


def drafts_qs():
    return (Draft.objects.filter(project=Project.current())
            .select_related("current_version", "source_reddit_post", "project"))


class DraftListView(generics.ListAPIView):
    """Inbox list. Filters: ?agent=reddit,x ?status=new|posted|dismissed ?sort=newest|score"""

    serializer_class = DraftListSerializer

    @extend_schema(parameters=[OpenApiParameter("agent", str), OpenApiParameter("status", str),
                               OpenApiParameter("sort", str, enum=["newest", "score"])])
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        qs = drafts_qs()
        params = self.request.query_params
        if agent := params.get("agent"):
            qs = qs.filter(agent_type__in=agent.split(","))
        qs = qs.filter(status=params.get("status") or Draft.Status.NEW)
        if params.get("sort") == "score":
            return qs.order_by(F("source_reddit_post__relevance_score").desc(nulls_last=True), "-created_at")
        return qs.order_by("-created_at")


class DraftDetailView(generics.RetrieveAPIView):
    serializer_class = DraftDetailSerializer

    def get_queryset(self):
        return drafts_qs().prefetch_related("versions")


class _DraftAction(APIView):
    def get_draft(self, pk) -> Draft:
        return generics.get_object_or_404(drafts_qs(), pk=pk)

    def detail(self, draft) -> Response:
        draft = drafts_qs().prefetch_related("versions").get(pk=draft.pk)
        return Response(DraftDetailSerializer(draft).data)


class EditView(_DraftAction):
    @extend_schema(request=EditSerializer, responses={200: DraftDetailSerializer})
    def post(self, request, pk):
        data = EditSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        draft = self.get_draft(pk)
        try:
            services.edit(draft, data.validated_data["content"])
        except services.DraftStateError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        except PydanticValidationError as exc:
            return Response({"content": exc.errors(include_url=False)}, status=status.HTTP_400_BAD_REQUEST)
        return self.detail(draft)


class RegenerateView(_DraftAction):
    @extend_schema(request=RegenerateSerializer, responses={202: AgentRunSerializer})
    def post(self, request, pk):
        data = RegenerateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        draft = self.get_draft(pk)
        if draft.status != Draft.Status.NEW:
            return Response({"detail": f"Can't regenerate a draft that is {draft.status}"},
                            status=status.HTTP_409_CONFLICT)
        # One regeneration per draft at a time; different drafts can regenerate in parallel.
        if AgentRun.objects.filter(kind=AgentRun.Kind.REGENERATE_DRAFT, status__in=AgentRun.ACTIVE,
                                   params__draft_id=draft.pk).exists():
            return Response({"detail": "This draft is already regenerating"}, status=status.HTTP_409_CONFLICT)
        run = AgentRun.objects.create(project=draft.project, kind=AgentRun.Kind.REGENERATE_DRAFT,
                                      params={"draft_id": draft.pk, **data.validated_data})
        transaction.on_commit(lambda: regenerate_draft_task.delay(run.id))
        return Response(AgentRunSerializer(run).data, status=status.HTTP_202_ACCEPTED)


class MarkPostedView(_DraftAction):
    @extend_schema(request=MarkPostedSerializer, responses={200: DraftDetailSerializer})
    def post(self, request, pk):
        data = MarkPostedSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        draft = self.get_draft(pk)
        services.mark_posted(draft, data.validated_data["posted_url"])
        return self.detail(draft)


class DismissView(_DraftAction):
    @extend_schema(request=DismissSerializer, responses={200: DraftDetailSerializer})
    def post(self, request, pk):
        data = DismissSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        draft = self.get_draft(pk)
        try:
            services.dismiss(draft, data.validated_data["reason"], data.validated_data["note"])
        except services.DraftStateError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        return self.detail(draft)


class RestoreView(_DraftAction):
    @extend_schema(request=None, responses={200: DraftDetailSerializer})
    def post(self, request, pk):
        draft = self.get_draft(pk)
        services.restore(draft)
        return self.detail(draft)


class ReadView(_DraftAction):
    @extend_schema(request=None, responses={204: None})
    def post(self, request, pk):
        services.mark_read(self.get_draft(pk))
        return Response(status=status.HTTP_204_NO_CONTENT)


class InboxCountsView(APIView):
    """Sidebar badges: unread in the inbox, and drafts ready (new) per agent."""

    @extend_schema(responses={200: dict})
    def get(self, request):
        new = Draft.objects.filter(project=Project.current(), status=Draft.Status.NEW)
        per_agent = dict(new.values_list("agent_type").annotate(n=Count("id")).values_list("agent_type", "n"))
        return Response({
            "unread": new.filter(read_at__isnull=True).count(),
            "ready": {a: per_agent.get(a, 0) for a in ("reddit", "content", "x")},
            "total_new": new.count(),
            "flagged": new.exclude(compliance_flags=[]).count(),
        })

