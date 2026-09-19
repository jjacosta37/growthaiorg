from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("apps.core.urls")),
    path("api/", include("apps.policy.urls")),
    path("api/", include("apps.agents.urls")),
    path("api/", include("apps.context.urls")),
    path("api/", include("apps.inbox.urls")),
    path("api/", include("apps.content.urls")),
    path("api/", include("apps.stats.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
]
