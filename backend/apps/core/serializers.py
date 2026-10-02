from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import Project, WaitlistSignup
from .selection import SESSION_KEY
from .validators import public_website_url


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(style={"input_type": "password"})


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = get_user_model()
        fields = ["id", "username", "email"]


class CompetitorSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    url = serializers.URLField(required=False, allow_blank=True, default="")


class ProjectSerializer(serializers.ModelSerializer):
    competitors = CompetitorSerializer(many=True, required=False)

    class Meta:
        model = Project
        fields = ["id", "name", "website_url", "product_summary", "competitors", "onboarded_at"]
        read_only_fields = ["id", "onboarded_at"]
        extra_kwargs = {"website_url": {"validators": [public_website_url]}}


class ProjectListSerializer(serializers.ModelSerializer):
    """A project in the switcher. `is_current` saves the frontend a second call."""

    is_current = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = ["id", "name", "website_url", "onboarded_at", "is_current", "created_at"]
        read_only_fields = ["id", "onboarded_at", "is_current", "created_at"]
        extra_kwargs = {"name": {"required": False}, "website_url": {"validators": [public_website_url]}}

    def get_is_current(self, obj) -> bool:
        request = self.context.get("request")
        return bool(request) and request.session.get(SESSION_KEY) == obj.pk

    def validate_name(self, value):
        return value.strip() or Project.DEFAULT_NAME

    def create(self, validated_data):
        validated_data.setdefault("name", Project.DEFAULT_NAME)
        return super().create(validated_data)


class WaitlistSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=WaitlistSignup._meta.get_field("email").max_length)
    source = serializers.CharField(max_length=40, required=False, allow_blank=True, default="")

    def validate_email(self, value):
        return value.strip().lower()
