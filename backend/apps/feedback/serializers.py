from rest_framework import serializers

from .models import AgentFeedback, AgentLearnings


class FeedbackEntrySerializer(serializers.ModelSerializer):
    """A feedback entry for the Learnings card, with the title of the draft it was on."""

    draft_title = serializers.SerializerMethodField()

    class Meta:
        model = AgentFeedback
        fields = ["id", "draft", "draft_title", "source", "rating", "text", "created_at", "digested_at"]

    def get_draft_title(self, obj: AgentFeedback) -> str:
        """The draft's inbox title, or "" once the draft is deleted."""
        from apps.inbox.serializers import draft_title

        return draft_title(obj.draft) if obj.draft else ""


class FeedbackCreateSerializer(serializers.Serializer):
    """Body of `POST /api/drafts/<id>/feedback/`: a rating, a comment, or both."""

    rating = serializers.ChoiceField(choices=AgentFeedback.Rating.choices, required=False, allow_blank=True,
                                     default="")
    text = serializers.CharField(required=False, allow_blank=True, default="", max_length=2000)

    def validate(self, data: dict) -> dict:
        """Refuse an empty submission."""
        if not data["rating"] and not data["text"].strip():
            raise serializers.ValidationError("Give a rating, a comment, or both")
        return data


class LearningsUpdateSerializer(serializers.Serializer):
    """Body of `PATCH /api/agents/<type>/learnings/`. Either field may be sent alone."""

    writing = serializers.CharField(required=False, allow_blank=True, max_length=4000, source="writing_md")
    selection = serializers.CharField(required=False, allow_blank=True, max_length=4000, source="selection_md")


class LearningsSerializer(serializers.ModelSerializer):
    """An agent's learnings, with the model's `_md` fields under their API names."""

    writing = serializers.CharField(source="writing_md")
    selection = serializers.CharField(source="selection_md")

    class Meta:
        model = AgentLearnings
        fields = ["writing", "selection", "source", "updated_at"]
