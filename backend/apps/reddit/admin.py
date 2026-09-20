from django.contrib import admin

from .models import RedditPost


@admin.register(RedditPost)
class RedditPostAdmin(admin.ModelAdmin):
    list_display = ("reddit_id", "project", "subreddit", "title", "relevance_score",
                    "reply_worthwhile", "posted_at")
    list_filter = ("project", "subreddit")
    search_fields = ("title", "reddit_id")
