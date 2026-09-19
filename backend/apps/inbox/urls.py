from django.urls import path

from . import views

urlpatterns = [
    path("inbox/counts/", views.InboxCountsView.as_view()),
    path("drafts/", views.DraftListView.as_view()),
    path("drafts/<int:pk>/", views.DraftDetailView.as_view()),
    path("drafts/<int:pk>/edit/", views.EditView.as_view()),
    path("drafts/<int:pk>/regenerate/", views.RegenerateView.as_view()),
    path("drafts/<int:pk>/mark-posted/", views.MarkPostedView.as_view()),
    path("drafts/<int:pk>/dismiss/", views.DismissView.as_view()),
    path("drafts/<int:pk>/restore/", views.RestoreView.as_view()),
    path("drafts/<int:pk>/read/", views.ReadView.as_view()),
]
