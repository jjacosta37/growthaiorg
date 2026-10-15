"""GitHub connection settings, and the Create PR / Update PR actions on a blog draft.

Everything is scoped through `current_project` (or, for the install callback, through the
signed state plus `owner=request.user`), so one tenant can't read or use another's
connection or PRs.
"""

from urllib.parse import urlencode

from django.conf import settings
from django.http import HttpResponseRedirect
from drf_spectacular.utils import extend_schema
from pydantic import ValidationError as PydanticValidationError
from rest_framework import generics, serializers, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.agents.serializers import AgentRunSerializer
from apps.core.errors import validation_errors
from apps.core.selection import current_project
from apps.inbox.models import Draft, DraftKind
from apps.inbox.views import drafts_qs
from providers.git_host import GitHostError

from . import connections, services
from .frontmatter import SAMPLE_POST, STANDARD_FIELDS, FrontmatterSettings, clean_folder, frontmatter, post_path
from .host import github_configured
from .models import GitHubConnection


def connection_data(conn: GitHubConnection | None) -> dict | None:
    if conn is None:
        return None
    return {
        "status": conn.status,
        "account": conn.account,
        "repo": conn.repo,
        "base_branch": conn.base_branch,
        "base_branch_protected": conn.base_branch_protected,
        "folder": conn.folder,
        "field_names": {f: conn.field_names.get(f, f) for f in STANDARD_FIELDS},
        "constant_fields": conn.constant_fields,
    }


def _connection_or_404(request: Request) -> GitHubConnection:
    from django.http import Http404

    conn = connections.connection_for(current_project(request))
    if conn is None:
        raise Http404("GitHub isn't connected")
    return conn


class GitHubStatusView(APIView):
    """GET: whether GitHub can be connected here, and this project's connection."""

    @extend_schema(responses={200: dict})
    def get(self, request: Request) -> Response:
        """The settings card's state."""
        conn = connections.connection_for(current_project(request))
        return Response({"available": github_configured(), "connection": connection_data(conn),
                         "standard_fields": list(STANDARD_FIELDS)})


class ConnectView(APIView):
    """POST: the GitHub install URL for this project (signed state inside)."""

    @extend_schema(request=None, responses={200: dict})
    def post(self, request: Request) -> Response:
        """Start connecting; 409 when this deployment has no GitHub App configured."""
        from .host import get_git_host

        if not github_configured():
            return Response({"detail": "GitHub isn't set up on this Luka server"}, status=status.HTTP_409_CONFLICT)
        state = connections.connect_state(request.user.pk, current_project(request))
        return Response({"url": get_git_host().install_url(state)})


class CallbackSerializer(serializers.Serializer):
    """What GitHub appends to the app's setup URL."""

    state = serializers.CharField(max_length=500, required=False, default="")
    code = serializers.CharField(max_length=200, required=False, default="")
    installation_id = serializers.IntegerField(required=False, min_value=1)
    setup_action = serializers.CharField(max_length=20, required=False, default="")


class CallbackView(APIView):
    """GET (browser, from GitHub): finish connecting, then return to Settings."""

    @extend_schema(parameters=[CallbackSerializer], responses={302: None})
    def get(self, request: Request) -> HttpResponseRedirect:
        """Verify and save the installation; the result rides back in `?github=`."""
        data = CallbackSerializer(data=request.query_params)
        if not data.is_valid():
            return self._back(error="GitHub sent back an unexpected answer. Try connecting again.")
        v = data.validated_data
        if v["setup_action"] == "request":
            return self._back(result="requested")  # an organisation owner must approve the install
        if "installation_id" not in v:
            return self._back(error="GitHub didn't say which installation to use. Try connecting again.")
        try:
            connections.complete_install(request.user, v["state"], v["code"], v["installation_id"])
        except connections.ConnectError as exc:
            return self._back(error=str(exc))
        return self._back(result="connected")

    def _back(self, *, result: str = "error", error: str = "") -> HttpResponseRedirect:
        params = {"github": result, **({"github_error": error} if error else {})}
        return HttpResponseRedirect(f"{settings.LUKA_APP_URL}/settings?{urlencode(params)}")


class ReposView(APIView):
    """GET: the repositories this project's installation can reach."""

    @extend_schema(responses={200: dict})
    def get(self, request: Request) -> Response:
        """Repositories with their default branch; 502-style detail when GitHub refuses."""
        conn = _connection_or_404(request)
        try:
            repos = connections.list_repos(conn)
        except GitHostError as exc:
            return Response({"detail": exc.reason, "status": conn.status}, status=status.HTTP_409_CONFLICT)
        return Response([{"full_name": r.full_name, "default_branch": r.default_branch} for r in repos])


class ConstantFieldSerializer(serializers.Serializer):
    key = serializers.CharField(max_length=40)
    value = serializers.JSONField()


class ConnectionSettingsSerializer(serializers.Serializer):
    """Body of `PATCH /api/github/connection/`."""

    repo = serializers.CharField(max_length=200)
    base_branch = serializers.CharField(max_length=200)
    folder = serializers.CharField(max_length=200, allow_blank=True, required=False, default="")
    field_names = serializers.DictField(child=serializers.CharField(max_length=40, allow_blank=True),
                                        required=False, default=dict)
    constant_fields = ConstantFieldSerializer(many=True, required=False, default=list)


class ConnectionView(APIView):
    """PATCH: save repository, base branch, folder and field settings. DELETE: disconnect."""

    @extend_schema(request=ConnectionSettingsSerializer, responses={200: dict})
    def patch(self, request: Request) -> Response:
        """Validate against GitHub and save; the connection is ready once this succeeds."""
        conn = _connection_or_404(request)
        data = ConnectionSettingsSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            conn = connections.save_settings(conn, **data.validated_data)
        except PydanticValidationError as exc:
            return Response({"fields": validation_errors(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except connections.ConnectError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(connection_data(conn))

    @extend_schema(responses={204: None})
    def delete(self, request: Request) -> Response:
        """Disconnect; nothing on GitHub changes."""
        connections.disconnect(current_project(request))
        return Response(status=status.HTTP_204_NO_CONTENT)


class PreviewSerializer(serializers.Serializer):
    """Body of `POST /api/github/preview/`: unsaved field settings to preview."""

    folder = serializers.CharField(max_length=200, allow_blank=True, required=False, default="")
    field_names = serializers.DictField(child=serializers.CharField(max_length=40, allow_blank=True),
                                        required=False, default=dict)
    constant_fields = ConstantFieldSerializer(many=True, required=False, default=list)


class PreviewView(APIView):
    """POST: the frontmatter and path a post would get with these settings."""

    @extend_schema(request=PreviewSerializer, responses={200: dict})
    def post(self, request: Request) -> Response:
        """Uses the project's latest blog draft, or a sample when it has none."""
        from django.utils import timezone

        data = PreviewSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        try:
            fm = FrontmatterSettings(field_names=v["field_names"], constant_fields=v["constant_fields"])
            folder = clean_folder(v["folder"])
        except PydanticValidationError as exc:
            return Response({"fields": validation_errors(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        latest = (Draft.objects.filter(project=current_project(request), kind=DraftKind.BLOG_POST)
                  .select_related("current_version").first())
        content = latest.current_version.content if latest and latest.current_version else SAMPLE_POST
        return Response({"path": post_path(folder, content["slug"]),
                         "frontmatter": frontmatter(content, fm, timezone.localdate()),
                         "from_draft": latest.pk if latest else None})


class _PullRequestAction(APIView):
    action = "create"

    @extend_schema(request=None, responses={202: AgentRunSerializer})
    def post(self, request: Request, pk: int) -> Response:
        """Queue the action; 409 with the reason when the draft can't take it now."""
        draft = generics.get_object_or_404(drafts_qs(request), pk=pk)
        try:
            run = services.request(draft, self.action)
        except services.PublishStateError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response(AgentRunSerializer(run).data, status=status.HTTP_202_ACCEPTED)


class CreatePullRequestView(_PullRequestAction):
    """POST: open (or retry opening) this blog draft's pull request."""

    action = "create"


class UpdatePullRequestView(_PullRequestAction):
    """POST: push the draft's current version to its pull request."""

    action = "update"
