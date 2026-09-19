from django.urls import path

from . import views

urlpatterns = [
    path("runs/", views.RunListView.as_view()),
    path("runs/<int:pk>/", views.RunDetailView.as_view()),
    path("runs/<int:pk>/events/", views.RunEventsView.as_view()),
]
