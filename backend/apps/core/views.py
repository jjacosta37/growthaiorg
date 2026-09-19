from django.contrib.auth import authenticate, login, logout
from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Project
from .serializers import LoginSerializer, ProjectSerializer, UserSerializer
from .status import build_status


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
    serializer_class = ProjectSerializer
    http_method_names = ["get", "patch"]

    def get_object(self):
        return Project.current()


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
        return Response(build_status(Project.current()))
