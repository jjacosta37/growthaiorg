from django.contrib import admin

from .models import DraftPullRequest, GitHubConnection


@admin.register(GitHubConnection)
class GitHubConnectionAdmin(admin.ModelAdmin):
    list_display = ("project", "account", "repo", "base_branch", "folder", "status", "updated_at")


@admin.register(DraftPullRequest)
class DraftPullRequestAdmin(admin.ModelAdmin):
    list_display = ("draft", "project", "state", "repo", "number", "updated_at")
