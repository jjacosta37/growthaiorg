import re

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.models import Project

from .models import ContentPolicy
from .packs import UnknownPack, all_packs, get_pack
from .service import apply_pack, policy_for


class RuleSerializer(serializers.Serializer):
    id = serializers.CharField(max_length=60)
    title = serializers.CharField(max_length=120)
    description = serializers.CharField(max_length=2000)

    def validate_id(self, value):
        if not re.fullmatch(r"[a-z][a-z0-9_]*", value):
            raise serializers.ValidationError("Use lowercase letters, digits and underscores")
        return value


class PolicySerializer(serializers.ModelSerializer):
    rules = RuleSerializer(many=True)
    disclosure_preview = serializers.SerializerMethodField()
    pack_name = serializers.SerializerMethodField()

    class Meta:
        model = ContentPolicy
        fields = ["pack", "pack_name", "source", "author_role", "rules", "disclosure", "disclosure_preview",
                  "blog_disclaimer", "updated_at"]
        read_only_fields = ["pack", "source", "updated_at"]

    def validate_rules(self, rules):
        ids = [r["id"] for r in rules]
        if len(ids) != len(set(ids)):
            raise serializers.ValidationError("Rule ids must be unique")
        return rules

    def get_disclosure_preview(self, obj) -> str:
        return obj.rendered_disclosure()

    def get_pack_name(self, obj) -> str:
        try:
            return get_pack(obj.pack).name
        except UnknownPack:
            return obj.pack


def sync_compliance_doc(project) -> None:
    from apps.context.documents import is_human_edited
    from apps.context.models import ContextDocument, DocKind
    from apps.context.pipeline import write_compliance_doc

    exists = ContextDocument.objects.filter(project=project, kind=DocKind.COMPLIANCE).exists()
    if exists and not is_human_edited(project, DocKind.COMPLIANCE):
        write_compliance_doc(project)


class PolicyView(APIView):
    """The project's content rules. PATCH edits them (marks the policy as user-owned)."""

    @extend_schema(responses={200: PolicySerializer})
    def get(self, request):
        return Response(PolicySerializer(policy_for(Project.current())).data)

    @extend_schema(request=PolicySerializer, responses={200: PolicySerializer})
    def patch(self, request):
        project = Project.current()
        policy = policy_for(project)
        data = PolicySerializer(policy, data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        policy = data.save(source=ContentPolicy.Source.USER)
        sync_compliance_doc(project)
        return Response(PolicySerializer(policy).data)


class PackListView(APIView):
    @extend_schema(responses={200: dict})
    def get(self, request):
        return Response([{"id": p.id, "name": p.name, "description": p.description, "rules": p.rules,
                          "blog_disclaimer": p.blog_disclaimer} for p in all_packs()])


class ApplyPackSerializer(serializers.Serializer):
    pack = serializers.CharField()


class ApplyPackView(APIView):
    """Replace the rules and disclaimer with a pack's (author role and disclosure wording are kept)."""

    @extend_schema(request=ApplyPackSerializer, responses={200: PolicySerializer})
    def post(self, request):
        data = ApplyPackSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        project = Project.current()
        try:
            policy = apply_pack(policy_for(project), data.validated_data["pack"], source=ContentPolicy.Source.USER)
        except UnknownPack:
            return Response({"pack": ["Unknown pack"]}, status=status.HTTP_400_BAD_REQUEST)
        sync_compliance_doc(project)
        return Response(PolicySerializer(policy).data)
