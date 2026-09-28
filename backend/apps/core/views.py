import logging

from django.contrib.auth import authenticate, login, logout
from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .models import Project, WaitlistSignup
from .selection import NoProjectSelected, current_project, select_project
from .serializers import (
    LoginSerializer,
    ProjectListSerializer,
    ProjectSerializer,
    UserSerializer,
    WaitlistSerializer,
)
from .status import build_status

log = logging.getLogger(__name__)


@method_decorator(ensure_csrf_cookie, name="dispatch")
class CsrfView(APIView):
    """Sets the csrftoken cookie so the SPA can send X-CSRFToken on unsafe requests."""

    permission_classes = [AllowAny]

    @extend_schema(responses={200: dict})
    def get(self, request):
        return Response({"csrfToken": get_token(request)})


class LoginView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(request=LoginSerializer, responses={200: UserSerializer})
    def post(self, request):
        data = LoginSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        user = authenticate(request, **data.validated_data)
        if user is None:
            return Response({"detail": "Invalid credentials."}, status=status.HTTP_400_BAD_REQUEST)
        login(request, user)
        return Response(UserSerializer(user).data)


class LogoutView(APIView):
    @extend_schema(request=None, responses={204: None})
    def post(self, request):
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    @extend_schema(responses={200: UserSerializer})
    def get(self, request):
        return Response(UserSerializer(request.user).data)


class ProjectView(generics.RetrieveUpdateAPIView):
    """The project the caller is currently working on."""

    serializer_class = ProjectSerializer
    http_method_names = ["get", "patch"]

    def get_object(self):
        return current_project(self.request)


class ProjectListCreateView(generics.ListCreateAPIView):
    """The caller's projects. Creating one also selects it, since that is always why."""

    serializer_class = ProjectListSerializer

    def get_queryset(self):
        # Settle the selection first, so a session that has never chosen one still gets an
        # `is_current` row. Without this the switcher opens with nothing marked current.
        try:
            current_project(self.request)
        except NoProjectSelected:
            pass  # a brand new account: the list is empty and there is nothing to select
        return Project.objects.filter(owner=self.request.user)

    def perform_create(self, serializer):
        project = serializer.save(owner=self.request.user)
        select_project(self.request, project)

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "request": self.request}


class ProjectSelectView(APIView):
    """Switch project. The frontend clears its cache afterwards: query keys are
    project-scoped but don't carry the project id."""

    @extend_schema(request=None, responses={200: ProjectListSerializer})
    def post(self, request, pk):
        project = generics.get_object_or_404(Project, pk=pk, owner=request.user)
        select_project(request, project)
        return Response(ProjectListSerializer(project, context={"request": request}).data)


class ProjectDeleteView(generics.DestroyAPIView):
    """Delete a project and everything under it.

    Domain rows cascade, but celery-beat rows are not related objects, so they are removed
    explicitly. Left behind, they'd fire every tick forever against a project id that no
    longer resolves.
    """

    serializer_class = ProjectListSerializer

    def get_queryset(self):
        return Project.objects.filter(owner=self.request.user)

    def perform_destroy(self, instance):
        from apps.agents.schedule import delete_periodic_tasks

        pk = instance.pk
        delete_periodic_tasks(instance)
        instance.delete()
        if self.request.session.get("project_id") == pk:
            self.request.session.pop("project_id", None)


class HealthView(APIView):
    """Unauthenticated liveness check for the load balancer: the app is up and the database answers."""

    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(responses={200: dict})
    def get(self, request):
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return Response({"ok": True})


class StatusView(APIView):
    """Background activity for the sidebar status line. Polled by the frontend."""

    @extend_schema(responses={200: dict})
    def get(self, request):
        return Response(build_status(current_project(request)))


class WaitlistView(APIView):
    """The landing page's waitlist form. Public and throttled per client.

    A repeat email answers the same as a new one, so the form can't be used to find out
    who is already on the list.
    """

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "waitlist"

    @extend_schema(request=WaitlistSerializer, responses={201: None})
    def post(self, request):
        data = WaitlistSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        signup, created = WaitlistSignup.objects.get_or_create(
            email=data.validated_data["email"],
            defaults={"source": data.validated_data["source"]},
        )
        if created:
            log.info("waitlist signup id=%s source=%s", signup.pk, signup.source or "-")
        return Response(status=status.HTTP_201_CREATED)
