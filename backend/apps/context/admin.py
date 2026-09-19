from django.contrib import admin

from .models import ContextDocument, ContextDocumentRevision, CrawledPage


@admin.register(ContextDocument)
class ContextDocumentAdmin(admin.ModelAdmin):
    list_display = ("kind", "source", "prompt_version", "model", "updated_at")


@admin.register(ContextDocumentRevision)
class ContextDocumentRevisionAdmin(admin.ModelAdmin):
    list_display = ("document", "source", "prompt_version", "created_at")


@admin.register(CrawledPage)
class CrawledPageAdmin(admin.ModelAdmin):
    list_display = ("url", "title", "fetched_at")
    search_fields = ("url", "title")
