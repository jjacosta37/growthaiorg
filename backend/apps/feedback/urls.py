from django.urls import path

from . import views

urlpatterns = [
    path("drafts/<int:pk>/feedback/", views.DraftFeedbackView.as_view()),
    path("agents/<str:agent_type>/learnings/", views.LearningsView.as_view()),
    path("agents/<str:agent_type>/learnings/rebuild/", views.LearningsRebuildView.as_view()),
    path("agents/<str:agent_type>/feedback/<int:pk>/", views.FeedbackEntryView.as_view()),
]
