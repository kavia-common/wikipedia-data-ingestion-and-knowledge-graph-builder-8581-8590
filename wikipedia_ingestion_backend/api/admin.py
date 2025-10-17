from django.contrib import admin
from .models import IngestionJob, IngestionItem


@admin.register(IngestionJob)
class IngestionJobAdmin(admin.ModelAdmin):
    """
    Admin configuration for IngestionJob.
    """
    list_display = (
        "id",
        "status",
        "processed_items",
        "total_items",
        "created_at",
        "updated_at",
    )
    list_filter = ("status", "created_at", "updated_at")
    search_fields = ("id",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(IngestionItem)
class IngestionItemAdmin(admin.ModelAdmin):
    """
    Admin configuration for IngestionItem.
    """
    list_display = (
        "id",
        "job",
        "source_type",
        "status",
        "result_page_title",
        "created_at",
        "updated_at",
    )
    list_filter = ("status", "source_type", "created_at", "updated_at")
    search_fields = ("id", "input_value", "result_page_title", "error_message")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("job",)
