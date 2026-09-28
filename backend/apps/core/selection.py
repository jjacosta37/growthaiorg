"""Which project does this request act on?

Every project-scoped queryset in the API filters on the result of `current_project`, and
no view defines object-level permissions. That makes this module the tenant boundary: if
it returns a project the caller doesn't own, nothing downstream would catch it.
"""

from rest_framework import status
from rest_framework.exceptions import APIException

from .models import Project

SESSION_KEY = "project_id"
HEADER = "HTTP_X_PROJECT_ID"

_CACHE_ATTR = "_luka_current_project"


class NoProjectSelected(APIException):
    """The user has no projects yet. The frontend answers this with the create-project screen."""

    status_code = status.HTTP_409_CONFLICT
    default_detail = "No project selected."
    default_code = "no_project"

    def __init__(self):
        # DRF drops the code when it renders, and a 409 here means something different
        # from "a run is already in progress" — so the code goes in the body explicitly.
        super().__init__({"detail": self.default_detail, "code": self.default_code})


def _owned(request, project_id) -> Project | None:
    """A project by id, but only if this user owns it.

    An id belonging to someone else is treated exactly like an absent one: we fall back to
    the caller's own project rather than raising. Distinguishing "not yours" from "doesn't
    exist" would confirm that the id is real.
    """
    if not project_id:
        return None
    try:
        return Project.objects.get(pk=int(project_id), owner=request.user)
    except (Project.DoesNotExist, TypeError, ValueError):
        return None


def current_project(request) -> Project:
    """The project this request acts on.

    In order: the X-Project-Id header, the session, then the user's first project. The
    header lets two browser tabs sit on different projects; the session keeps the
    browsable API usable without one.
    """
    cached = getattr(request, _CACHE_ATTR, None)
    if cached is not None:
        return cached

    project = _owned(request, request.META.get(HEADER)) or _owned(
        request, request.session.get(SESSION_KEY)
    )

    if project is None:
        project = Project.objects.filter(owner=request.user).first()
        if project is None:
            raise NoProjectSelected()
        select_project(request, project)

    setattr(request, _CACHE_ATTR, project)
    return project


def select_project(request, project: Project) -> None:
    """Remember this project for later requests in the same session."""
    request.session[SESSION_KEY] = project.pk
    setattr(request, _CACHE_ATTR, project)


class ProjectScopedMixin:
    """For DRF generic views: `self.project` is the caller's current project."""

    @property
    def project(self) -> Project:
        return current_project(self.request)
