from django.contrib import admin

from .models import RedditPost, RedditTargetSuggestion


@admin.register(RedditPost)
class RedditPostAdmin(admin.ModelAdmin):
    list_display = ("reddit_id", "project", "subreddit", "title", "relevance_score",
                    "reply_worthwhile", "posted_at")
    list_filter = ("project", "subreddit")
    search_fields = ("title", "reddit_id")


@admin.register(RedditTargetSuggestion)
class RedditTargetSuggestionAdmin(admin.ModelAdmin):
    list_display = ("value", "kind", "status", "project", "created_at")
    list_filter = ("project", "kind", "status")
