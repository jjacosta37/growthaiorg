from django.contrib import admin

from .models import Project, WaitlistSignup


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "website_url", "onboarded_at")
    list_filter = ("owner",)
    search_fields = ("name", "website_url")


@admin.register(WaitlistSignup)
class WaitlistSignupAdmin(admin.ModelAdmin):
    list_display = ("email", "source", "created_at")
    list_filter = ("source",)
    search_fields = ("email",)
    readonly_fields = ("created_at",)
