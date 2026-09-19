from rest_framework import serializers

from .content import X_CHAR_LIMIT, as_text
from .models import Draft, DraftVersion
from .nudges import NUDGES


def draft_title(draft: Draft) -> str:
    content = draft.current_version.content if draft.current_version else {}
    if draft.kind == "reddit_comment" and draft.source_reddit_post:
        return draft.source_reddit_post.title
    if draft.kind in ("x_post", "x_thread") and content.get("posts"):
        return content["posts"][0][:120]
    return content.get("title", "")


class DraftListSerializer(serializers.ModelSerializer):
    title = serializers.SerializerMethodField()
    channel = serializers.CharField(source="agent_type")
    score = serializers.IntegerField(source="source_reddit_post.relevance_score", default=None)
    subreddit = serializers.CharField(source="source_reddit_post.subreddit", default=None)
    unread = serializers.SerializerMethodField()
    flag_count = serializers.SerializerMethodField()

    class Meta:
        model = Draft
        fields = ["id", "channel", "kind", "status", "title", "score", "subreddit", "unread", "flag_count",
                  "created_at"]

    def get_title(self, obj) -> str:
        return draft_title(obj)

    def get_unread(self, obj) -> bool:
        return obj.read_at is None and obj.status == Draft.Status.NEW

    def get_flag_count(self, obj) -> int:
        return len(obj.compliance_flags)


class DraftVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = DraftVersion
        fields = ["id", "n", "source", "content", "nudge", "instruction", "prompt_name", "prompt_version", "model",
                  "created_at"]


class RedditSourceSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    subreddit = serializers.CharField()
    title = serializers.CharField()
    body = serializers.CharField()
    url = serializers.URLField()
    author = serializers.CharField()
    upvotes = serializers.IntegerField()
    num_comments = serializers.IntegerField()
    posted_at = serializers.DateTimeField()
    relevance_score = serializers.IntegerField()
    relevance_reason = serializers.CharField()


class DraftDetailSerializer(DraftListSerializer):
    content = serializers.JSONField(source="current_version.content")
    copy_text = serializers.SerializerMethodField()
    open_url = serializers.SerializerMethodField()
    source_post = RedditSourceSerializer(source="source_reddit_post", default=None)
    versions = DraftVersionSerializer(many=True)
    char_limit = serializers.SerializerMethodField()

    class Meta(DraftListSerializer.Meta):
        fields = [*DraftListSerializer.Meta.fields, "content", "copy_text", "open_url", "source_post",
                  "compliance_flags", "versions", "char_limit", "posted_at", "posted_url", "dismiss_reason",
                  "dismiss_note"]

    def get_copy_text(self, obj) -> str:
        return as_text(obj.kind, obj.current_version.content)

    def get_open_url(self, obj) -> str:
        """Where "Copy & open" sends me."""
        if obj.kind == "reddit_comment" and obj.source_reddit_post:
            return obj.source_reddit_post.url
        if obj.kind in ("x_post", "x_thread"):
            return "https://x.com/compose/post"
        return ""

    def get_char_limit(self, obj) -> int | None:
        return X_CHAR_LIMIT if obj.kind in ("x_post", "x_thread") else None


class EditSerializer(serializers.Serializer):
    content = serializers.JSONField()


class RegenerateSerializer(serializers.Serializer):
    nudge = serializers.ChoiceField(choices=list(NUDGES), required=False, allow_blank=True, default="")
    instruction = serializers.CharField(required=False, allow_blank=True, default="", max_length=2000)

    def validate(self, data):
        if data["nudge"] == "custom" and not data["instruction"].strip():
            raise serializers.ValidationError("A custom nudge needs an instruction")
        return data


class MarkPostedSerializer(serializers.Serializer):
    posted_url = serializers.URLField(required=False, allow_blank=True, default="")


class DismissSerializer(serializers.Serializer):
    reason = serializers.ChoiceField(choices=Draft.DismissReason.choices)
    note = serializers.CharField(required=False, allow_blank=True, default="", max_length=2000)
