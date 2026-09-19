from django.contrib import admin

from .models import ContentPolicy


@admin.register(ContentPolicy)
class ContentPolicyAdmin(admin.ModelAdmin):
    list_display = ("project", "pack", "source", "author_role", "updated_at")
