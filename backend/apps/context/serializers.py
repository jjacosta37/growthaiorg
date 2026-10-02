from rest_framework import serializers

from apps.core.validators import public_website_url

from .models import ContextDocument, ContextDocumentRevision, CrawledPage, DocKind


class ContextDocumentSerializer(serializers.ModelSerializer):
    title = serializers.CharField(read_only=True)

    class Meta:
        model = ContextDocument
        fields = ["kind", "title", "content_md", "source", "prompt_version", "model", "updated_at"]
        read_only_fields = ["kind", "source", "prompt_version", "model", "updated_at"]


class ContextDocumentRevisionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContextDocumentRevision
        fields = ["id", "content_md", "source", "prompt_version", "model", "created_at"]


class CrawledPageSerializer(serializers.ModelSerializer):
    chars = serializers.SerializerMethodField()

    class Meta:
        model = CrawledPage
        fields = ["id", "url", "title", "chars", "fetched_at"]

    def get_chars(self, obj) -> int:
        return len(obj.content_text)


class StartOnboardingSerializer(serializers.Serializer):
    website_url = serializers.URLField(validators=[public_website_url])
    name = serializers.CharField(required=False, max_length=120, help_text="Product name (detected if omitted)")
    max_pages = serializers.IntegerField(required=False, min_value=1, max_value=200)


class RecrawlSerializer(serializers.Serializer):
    overwrite_edited = serializers.BooleanField(default=False)
    max_pages = serializers.IntegerField(required=False, min_value=1, max_value=200)


def doc_kind_or_404(kind: str) -> str:
    from django.http import Http404

    if kind not in DocKind.values:
        raise Http404(f"Unknown document kind {kind!r}")
    return kind
