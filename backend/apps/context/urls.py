from django.urls import path

from . import views

urlpatterns = [
    path("onboarding/start/", views.StartOnboardingView.as_view()),
    path("context/recrawl/", views.RecrawlView.as_view()),
    path("context/pages/", views.CrawledPageListView.as_view()),
    path("context/docs/", views.DocumentListView.as_view()),
    path("context/docs/<str:kind>/", views.DocumentDetailView.as_view()),
    path("context/docs/<str:kind>/regenerate/", views.RegenerateDocumentView.as_view()),
    path("context/docs/<str:kind>/revisions/", views.DocumentRevisionsView.as_view()),
]
