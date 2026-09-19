from django.urls import path

from . import views

urlpatterns = [
    path("agents/content/topics/", views.TopicListView.as_view()),
    path("agents/content/topics/<int:pk>/draft/", views.TopicDraftView.as_view()),
    path("agents/content/topics/<int:pk>/reject/", views.TopicRejectView.as_view()),
]
