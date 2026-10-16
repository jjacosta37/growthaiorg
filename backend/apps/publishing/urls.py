from django.urls import path

from . import views

urlpatterns = [
    path("github/", views.GitHubStatusView.as_view()),
    path("github/connect/", views.ConnectView.as_view()),
    path("github/callback/", views.CallbackView.as_view()),
    path("github/repos/", views.ReposView.as_view()),
    path("github/connection/", views.ConnectionView.as_view()),
    path("github/preview/", views.PreviewView.as_view()),
    path("drafts/<int:pk>/pull-request/", views.CreatePullRequestView.as_view()),
    path("drafts/<int:pk>/pull-request/update/", views.UpdatePullRequestView.as_view()),
]
