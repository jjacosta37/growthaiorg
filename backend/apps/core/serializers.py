from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import Project


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
