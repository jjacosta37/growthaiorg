from django.contrib import admin

from .models import Project


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "website_url", "onboarded_at")
    list_filter = ("owner",)
    search_fields = ("name", "website_url")
