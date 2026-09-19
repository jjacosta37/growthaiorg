from django.urls import path

from . import views

urlpatterns = [
    path("policy/", views.PolicyView.as_view()),
    path("policy/packs/", views.PackListView.as_view()),
    path("policy/apply-pack/", views.ApplyPackView.as_view()),
]
