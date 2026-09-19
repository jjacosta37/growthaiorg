from django.urls import path

from . import views

urlpatterns = [
    path("runs/", views.RunListView.as_view()),
    path("runs/<int:pk>/", views.RunDetailView.as_view()),
    path("runs/<int:pk>/events/", views.RunEventsView.as_view()),
]

from . import api  # noqa: E402

urlpatterns += [
    path("agents/", api.AgentListView.as_view()),
    path("agents/reddit/skipped/", api.RedditSkippedView.as_view()),
    path("agents/<str:agent_type>/", api.AgentDetailView.as_view()),
    path("agents/<str:agent_type>/run-now/", api.RunNowView.as_view()),
    path("agents/<str:agent_type>/runs/", api.AgentRunsView.as_view()),
]
