from django.contrib import admin

from .models import BlogTopic


@admin.register(BlogTopic)
class BlogTopicAdmin(admin.ModelAdmin):
    list_display = ("title", "project", "status", "requested_by_user", "created_at")
    list_filter = ("project", "status", "requested_by_user")
    search_fields = ("title",)
