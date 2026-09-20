from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.selection import current_project

from .service import build_stats


class StatsView(APIView):
    """Weekly drafts per agent (generated/posted/dismissed), dismiss reasons, LLM + Apify spend.
    ?weeks=8 (1-52)."""

    @extend_schema(parameters=[OpenApiParameter("weeks", int)], responses={200: dict})
    def get(self, request):
        try:
            weeks = min(52, max(1, int(request.query_params.get("weeks", 8))))
        except ValueError:
            weeks = 8
        return Response(build_stats(current_project(request), weeks))
