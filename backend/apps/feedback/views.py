from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.agents.api import spec_or_404
from apps.agents.models import AgentRun
from apps.core.selection import current_project
from apps.inbox.serializers import DraftDetailSerializer
from apps.inbox.views import drafts_qs

from . import services
from .models import AgentFeedback, AgentLearnings
from .serializers import (
    FeedbackCreateSerializer,
    FeedbackEntrySerializer,
    LearningsSerializer,
    LearningsUpdateSerializer,
)

ENTRIES_SHOWN = 50


class DraftFeedbackView(APIView):
    """POST {rating?, text?}: feedback on a draft, remembered for the agent's future drafts."""

    @extend_schema(request=FeedbackCreateSerializer, responses={200: DraftDetailSerializer})
    def post(self, request, pk):
        data = FeedbackCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        draft = generics.get_object_or_404(drafts_qs(request), pk=pk)
        services.record(draft, source=AgentFeedback.Source.EXPLICIT, **data.validated_data)
        draft = drafts_qs(request).prefetch_related("versions", "feedback").get(pk=draft.pk)
        return Response(DraftDetailSerializer(draft).data)


def learnings_payload(project, agent_type: str) -> dict:
    learnings = AgentLearnings.for_project(project, agent_type)
    entries = (AgentFeedback.objects.filter(project=project, agent_type=agent_type)
               .select_related("draft__current_version", "draft__source_reddit_post")[:ENTRIES_SHOWN])
    digesting = AgentRun.objects.filter(project=project, kind=AgentRun.Kind.DIGEST_FEEDBACK,
                                        status__in=AgentRun.ACTIVE, params__agent_type=agent_type).exists()
    return {
        **LearningsSerializer(learnings).data,
        "pending": services.pending(project, agent_type).count(),
        "digesting": digesting,
        "entries": FeedbackEntrySerializer(entries, many=True).data,
    }


class LearningsView(APIView):
    """GET the agent's learnings and feedback; PATCH {writing?, selection?} to edit them by hand."""

    @extend_schema(responses={200: dict})
    def get(self, request, agent_type):
        spec = spec_or_404(agent_type)
        return Response(learnings_payload(current_project(request), spec.agent_type))

    @extend_schema(request=LearningsUpdateSerializer, responses={200: dict})
    def patch(self, request, agent_type):
        spec = spec_or_404(agent_type)
        project = current_project(request)
        data = LearningsUpdateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        learnings = AgentLearnings.for_project(project, spec.agent_type)
        for field, value in data.validated_data.items():
            setattr(learnings, field, value.strip())
        learnings.source = AgentLearnings.Source.HUMAN
        learnings.save()
        return Response(learnings_payload(project, spec.agent_type))


class LearningsRebuildView(APIView):
    """Re-learn from every feedback entry, replacing the current learnings."""

    @extend_schema(request=None, responses={202: dict})
    def post(self, request, agent_type):
        spec = spec_or_404(agent_type)
        project = current_project(request)
        transaction.on_commit(lambda: services.schedule_digest(project.pk, spec.agent_type, rebuild=True))
        return Response(learnings_payload(project, spec.agent_type), status=status.HTTP_202_ACCEPTED)


class FeedbackEntryView(APIView):
    @extend_schema(responses={204: None})
    def delete(self, request, agent_type, pk):
        spec = spec_or_404(agent_type)
        entry = generics.get_object_or_404(
            AgentFeedback.objects.filter(project=current_project(request), agent_type=spec.agent_type), pk=pk)
        entry.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
