from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.models import Project

from .models import AgentRun
from .serializers import AgentRunSerializer, RunEventSerializer


class RunListView(generics.ListAPIView):
    serializer_class = AgentRunSerializer

    def get_queryset(self):
        qs = AgentRun.objects.filter(project=Project.current())
        if kind := self.request.query_params.get("kind"):
            qs = qs.filter(kind__in=kind.split(","))
        return qs


class RunDetailView(generics.RetrieveAPIView):
    serializer_class = AgentRunSerializer

    def get_queryset(self):
        return AgentRun.objects.filter(project=Project.current())


class RunEventsView(APIView):
    """Events for a run. Pass ?after=<last event id> to poll incrementally."""

    @extend_schema(parameters=[OpenApiParameter("after", int)], responses={200: RunEventSerializer(many=True)})
    def get(self, request, pk):
        run = generics.get_object_or_404(AgentRun, pk=pk, project=Project.current())
        events = run.events.all()
        if after := request.query_params.get("after"):
            events = events.filter(id__gt=int(after))
        return Response(RunEventSerializer(events, many=True).data)
