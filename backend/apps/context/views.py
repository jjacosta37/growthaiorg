from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.agents.models import AgentRun
from apps.agents.runs import RunConflict, create_run
from apps.agents.serializers import AgentRunSerializer
from apps.core.models import Project

from .documents import ordered_documents, save_document
from .models import ContextDocument, CrawledPage, DocSource
from .serializers import (
    ContextDocumentRevisionSerializer,
    ContextDocumentSerializer,
    CrawledPageSerializer,
    RecrawlSerializer,
    StartOnboardingSerializer,
    doc_kind_or_404,
)
from .tasks import onboarding_task, regenerate_document_task

# Only one context-changing run at a time: they all write the same documents.
CONTEXT_RUN_KINDS = (AgentRun.Kind.ONBOARDING, AgentRun.Kind.RECRAWL, AgentRun.Kind.REGENERATE_DOC)


def _start(project, kind, params, task) -> Response:
    try:
        run = create_run(project, kind, params=params, exclusive_kinds=CONTEXT_RUN_KINDS)
    except RunConflict as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
    transaction.on_commit(lambda: task.delay(run.id))
    return Response(AgentRunSerializer(run).data, status=status.HTTP_202_ACCEPTED)


class StartOnboardingView(APIView):
    @extend_schema(request=StartOnboardingSerializer, responses={202: AgentRunSerializer})
    def post(self, request):
        data = StartOnboardingSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        project = Project.current()
        project.website_url = data.validated_data["website_url"]
        project.save(update_fields=["website_url"])
        params = {"max_pages": data.validated_data.get("max_pages")}
        return _start(project, AgentRun.Kind.ONBOARDING, params, onboarding_task)


class RecrawlView(APIView):
    @extend_schema(request=RecrawlSerializer, responses={202: AgentRunSerializer})
    def post(self, request):
        data = RecrawlSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        project = Project.current()
        if not project.website_url:
            return Response({"detail": "Run onboarding first."}, status=status.HTTP_400_BAD_REQUEST)
        return _start(project, AgentRun.Kind.RECRAWL, dict(data.validated_data), onboarding_task)


class DocumentListView(APIView):
    @extend_schema(responses={200: ContextDocumentSerializer(many=True)})
    def get(self, request):
        docs = ordered_documents(Project.current())
        return Response(ContextDocumentSerializer(docs, many=True).data)


class DocumentDetailView(generics.RetrieveUpdateAPIView):
    """GET a document; PATCH {content_md} saves a human edit (a new revision)."""

    serializer_class = ContextDocumentSerializer
    http_method_names = ["get", "patch"]

    def get_object(self):
        kind = doc_kind_or_404(self.kwargs["kind"])
        return generics.get_object_or_404(ContextDocument, project=Project.current(), kind=kind)

    def perform_update(self, serializer):
        doc = self.get_object()
        serializer.instance = save_document(
            doc.project, doc.kind, serializer.validated_data.get("content_md", doc.content_md),
            source=DocSource.HUMAN,
        )


class RegenerateDocumentView(APIView):
    @extend_schema(request=None, responses={202: AgentRunSerializer})
    def post(self, request, kind):
        kind = doc_kind_or_404(kind)
        return _start(Project.current(), AgentRun.Kind.REGENERATE_DOC, {"kind": kind}, regenerate_document_task)


class DocumentRevisionsView(generics.ListAPIView):
    serializer_class = ContextDocumentRevisionSerializer
    pagination_class = None

    def get_queryset(self):
        kind = doc_kind_or_404(self.kwargs["kind"])
        doc = generics.get_object_or_404(ContextDocument, project=Project.current(), kind=kind)
        return doc.revisions.order_by("-id")


class CrawledPageListView(generics.ListAPIView):
    serializer_class = CrawledPageSerializer
    pagination_class = None

    def get_queryset(self):
        return CrawledPage.objects.filter(project=Project.current())
