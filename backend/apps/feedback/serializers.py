from rest_framework import serializers

from .models import AgentFeedback, AgentLearnings


class FeedbackEntrySerializer(serializers.ModelSerializer):
    draft_title = serializers.SerializerMethodField()

    class Meta:
        model = AgentFeedback
        fields = ["id", "draft", "draft_title", "source", "rating", "text", "created_at", "digested_at"]

    def get_draft_title(self, obj) -> str:
        from apps.inbox.serializers import draft_title

        return draft_title(obj.draft) if obj.draft else ""


class FeedbackCreateSerializer(serializers.Serializer):
    rating = serializers.ChoiceField(choices=AgentFeedback.Rating.choices, required=False, allow_blank=True,
                                     default="")
    text = serializers.CharField(required=False, allow_blank=True, default="", max_length=2000)

    def validate(self, data):
        if not data["rating"] and not data["text"].strip():
            raise serializers.ValidationError("Give a rating, a comment, or both")
        return data


class LearningsUpdateSerializer(serializers.Serializer):
    writing = serializers.CharField(required=False, allow_blank=True, max_length=4000, source="writing_md")
    selection = serializers.CharField(required=False, allow_blank=True, max_length=4000, source="selection_md")


class LearningsSerializer(serializers.ModelSerializer):
    writing = serializers.CharField(source="writing_md")
    selection = serializers.CharField(source="selection_md")

    class Meta:
        model = AgentLearnings
        fields = ["writing", "selection", "source", "updated_at"]
