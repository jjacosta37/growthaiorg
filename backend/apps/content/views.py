from django.db import transaction
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.agents.models import AgentRun
from apps.agents.runs import RunConflict, create_run
from apps.agents.serializers import AgentRunSerializer
from apps.agents.tasks import run_agent_task
from apps.core.models import Project

from .models import BlogTopic


class BlogTopicSerializer(serializers.ModelSerializer):
    draft_id = serializers.SerializerMethodField()

    class Meta:
        model = BlogTopic
        fields = ["id", "title", "angle", "target_keywords", "pillar", "why", "status", "requested_by_user",
                  "draft_id", "created_at"]
        read_only_fields = ["pillar", "why", "status", "requested_by_user", "draft_id", "created_at"]

    def get_draft_id(self, obj) -> int | None:
        draft = obj.drafts.order_by("-created_at").first()
        return draft.id if draft else None


class RequestTopicSerializer(BlogTopicSerializer):
    draft_now = serializers.BooleanField(default=True, write_only=True)

    class Meta(BlogTopicSerializer.Meta):
        fields = [*BlogTopicSerializer.Meta.fields, "draft_now"]


def start_draft_run(topic: BlogTopic) -> AgentRun:
    run = create_run(topic.project, AgentRun.Kind.CONTENT, trigger=AgentRun.Trigger.MANUAL,
                     params={"topic_id": topic.pk})
    transaction.on_commit(lambda: run_agent_task.delay(run.id))
    return run


class TopicListView(generics.ListCreateAPIView):
    """GET the topic backlog (?status=proposed|drafted|rejected). POST requests a specific topic;
    with draft_now (default) it's drafted right away."""

    def get_serializer_class(self):
        return RequestTopicSerializer if self.request.method == "POST" else BlogTopicSerializer

    @extend_schema(parameters=[OpenApiParameter("status", str)])
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        qs = BlogTopic.objects.filter(project=Project.current()).prefetch_related("drafts").order_by("-created_at")
        if s := self.request.query_params.get("status"):
            qs = qs.filter(status=s)
        return qs

    @extend_schema(request=RequestTopicSerializer, responses={201: dict})
    def post(self, request, *args, **kwargs):
        data = RequestTopicSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = dict(data.validated_data)
        draft_now = v.pop("draft_now")
        with transaction.atomic():
            topic = BlogTopic.objects.create(project=Project.current(), requested_by_user=True, **v)
            run = None
            if draft_now:
                try:
                    run = start_draft_run(topic)
                except RunConflict as exc:
                    return Response({"detail": f"{exc}. The topic was saved to the backlog.",
                                     "topic": BlogTopicSerializer(topic).data}, status=status.HTTP_409_CONFLICT)
        return Response({"topic": BlogTopicSerializer(topic).data,
                         "run": AgentRunSerializer(run).data if run else None}, status=status.HTTP_201_CREATED)


class TopicDraftView(APIView):
    @extend_schema(request=None, responses={202: AgentRunSerializer})
    def post(self, request, pk):
        topic = generics.get_object_or_404(BlogTopic, pk=pk, project=Project.current())
        if topic.status == BlogTopic.Status.REJECTED:
            return Response({"detail": "Topic was rejected"}, status=status.HTTP_409_CONFLICT)
        try:
            run = start_draft_run(topic)
        except RunConflict as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response(AgentRunSerializer(run).data, status=status.HTTP_202_ACCEPTED)


class TopicRejectView(APIView):
    @extend_schema(request=None, responses={200: BlogTopicSerializer})
    def post(self, request, pk):
        topic = generics.get_object_or_404(BlogTopic, pk=pk, project=Project.current())
        topic.status = BlogTopic.Status.REJECTED
        topic.save(update_fields=["status", "updated_at"])
        return Response(BlogTopicSerializer(topic).data)
