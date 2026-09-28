from django.urls import path

from . import views

urlpatterns = [
    path("auth/csrf/", views.CsrfView.as_view()),
    path("auth/login/", views.LoginView.as_view()),
    path("auth/logout/", views.LogoutView.as_view()),
    path("auth/me/", views.MeView.as_view()),
    path("project/", views.ProjectView.as_view()),
    path("projects/", views.ProjectListCreateView.as_view()),
    path("projects/<int:pk>/", views.ProjectDeleteView.as_view()),
    path("projects/<int:pk>/select/", views.ProjectSelectView.as_view()),
    path("status/", views.StatusView.as_view()),
    path("health/", views.HealthView.as_view()),
    path("waitlist/", views.WaitlistView.as_view()),
]
