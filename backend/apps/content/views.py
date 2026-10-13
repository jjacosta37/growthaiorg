from django.db import transaction
from django.db.models import F, Prefetch, QuerySet
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, serializers, status
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.agents.models import AgentRun
from apps.agents.runs import RunConflict, create_run
from apps.agents.serializers import AgentRunSerializer
from apps.agents.tasks import run_agent_task
from apps.core.selection import current_project
from apps.core.text import http_url
from apps.reddit.models import RedditPost

from .models import BlogTopic
from .opportunity import rank_topics, with_evidence_count
from .pipeline import load_config

SORTS = {
    "volume": [F("search_volume").desc(nulls_last=True), "-created_at"],
    "difficulty": [F("keyword_difficulty").asc(nulls_last=True), "-created_at"],
    "evidence": ["-evidence_count", "-created_at"],
    "newest": ["-created_at"],
}


class EvidencePostSerializer(serializers.Serializer):
    """A Reddit post behind a topic. The URL is only ever an http(s) link."""

    id = serializers.IntegerField()
    subreddit = serializers.CharField()
    title = serializers.CharField()
    url = serializers.SerializerMethodField()

    def get_url(self, obj: RedditPost) -> str:
        """The post's link, or "" if it isn't http(s)."""
        return http_url(obj.url)


class BlogTopicSerializer(serializers.ModelSerializer):
    """A backlog topic with its Reddit evidence and its primary keyword's search data."""

    draft_id = serializers.SerializerMethodField()
    target_keywords = serializers.ListField(child=serializers.CharField(max_length=80), max_length=5,
                                            required=False)
    evidence = EvidencePostSerializer(source="evidence_posts", many=True, read_only=True)
    evidence_count = serializers.SerializerMethodField()
    low_volume = serializers.BooleanField(read_only=True)

    class Meta:
        model = BlogTopic
        fields = ["id", "title", "angle", "target_keywords", "pillar", "why", "status", "requested_by_user",
                  "draft_id", "created_at", "evidence", "evidence_count", "search_status", "primary_keyword",
                  "search_volume", "keyword_difficulty", "search_market", "low_volume"]
        read_only_fields = ["pillar", "why", "status", "requested_by_user", "draft_id", "created_at",
                            "search_status", "primary_keyword", "search_volume", "keyword_difficulty",
                            "search_market"]

    def get_draft_id(self, obj) -> int | None:
        draft = obj.drafts.order_by("-created_at").first()
        return draft.id if draft else None

    def get_evidence_count(self, obj: BlogTopic) -> int:
        """How many Reddit posts back the topic."""
        return len(obj.evidence_posts.all())


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
    """GET the topic backlog (?status=proposed|drafted|rejected, ?sort=opportunity|volume|difficulty|
    evidence|newest). POST requests a specific topic; with draft_now (default) it's drafted right away."""

    def get_serializer_class(self):
        return RequestTopicSerializer if self.request.method == "POST" else BlogTopicSerializer

    @extend_schema(parameters=[OpenApiParameter("status", str), OpenApiParameter("sort", str)])
    def get(self, request: Request, *args, **kwargs) -> Response:
        """GET the backlog; the default sort is the drafting order (opportunity)."""
        return super().get(request, *args, **kwargs)

    def get_queryset(self) -> QuerySet[BlogTopic] | list[BlogTopic]:
        """The project's topics in the requested order; `opportunity` is ranked in Python."""
        project = current_project(self.request)
        sort = self.request.query_params.get("sort", "opportunity")
        if sort != "opportunity" and sort not in SORTS:
            raise ValidationError({"sort": [f"Must be one of: opportunity, {', '.join(SORTS)}"]})
        qs = with_evidence_count(BlogTopic.objects.filter(project=project)).prefetch_related(
            "drafts", Prefetch("evidence_posts", queryset=RedditPost.objects.filter(project=project)))
        if s := self.request.query_params.get("status"):
            qs = qs.filter(status=s)
        if sort == "opportunity":
            return rank_topics(qs, load_config(project).weights)
        return qs.order_by(*SORTS[sort])

    @extend_schema(request=RequestTopicSerializer, responses={201: dict})
    def post(self, request, *args, **kwargs):
        data = RequestTopicSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = dict(data.validated_data)
        draft_now = v.pop("draft_now")
        with transaction.atomic():
            topic = BlogTopic.objects.create(project=current_project(request), requested_by_user=True, **v)
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
        topic = generics.get_object_or_404(BlogTopic, pk=pk, project=current_project(request))
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
        topic = generics.get_object_or_404(BlogTopic, pk=pk, project=current_project(request))
        topic.status = BlogTopic.Status.REJECTED
        topic.save(update_fields=["status", "updated_at"])
        return Response(BlogTopicSerializer(topic).data)
