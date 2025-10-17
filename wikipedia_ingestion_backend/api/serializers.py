from __future__ import annotations

from rest_framework import serializers

from .models import IngestionItem, IngestionJob


class IngestionItemSerializer(serializers.ModelSerializer):
    """Serializer for IngestionItem model."""

    class Meta:
        model = IngestionItem
        fields = [
            "id",
            "job",
            "input_value",
            "source_type",
            "status",
            "result_page_title",
            "error_message",
            "meta",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "result_page_title",
            "error_message",
            "created_at",
            "updated_at",
        ]


class IngestionJobSerializer(serializers.ModelSerializer):
    """Serializer for IngestionJob model."""

    items = serializers.SerializerMethodField(read_only=True)

    def get_items(self, obj: IngestionJob) -> int:
        return obj.items.count()

    class Meta:
        model = IngestionJob
        fields = [
            "id",
            "status",
            "total_items",
            "processed_items",
            "error_message",
            "config",
            "created_at",
            "updated_at",
            "items",
        ]
        read_only_fields = [
            "id",
            "status",
            "total_items",
            "processed_items",
            "error_message",
            "created_at",
            "updated_at",
            "items",
        ]


class UploadCSVRequestSerializer(serializers.Serializer):
    """Request serializer for uploading a CSV file to create a job."""

    csv_file = serializers.FileField(help_text="CSV file containing topics or Wikipedia links.")
    column_name = serializers.CharField(
        required=False, allow_blank=True, help_text="Optional column name; first column used by default."
    )
    has_header = serializers.BooleanField(
        required=False, default=True, help_text="Whether the CSV includes a header row."
    )
    config = serializers.JSONField(
        required=False,
        help_text="Optional JSON configuration for the job (stored in job.config).",
    )


class SingleIngestRequestSerializer(serializers.Serializer):
    """Request serializer for ingesting a single topic or link into a new job."""

    value = serializers.CharField(help_text="Topic or direct Wikipedia URL.")
    source_type = serializers.ChoiceField(
        required=False,
        choices=[ch[0] for ch in IngestionItem.SourceType.choices],
        help_text="Override classification; otherwise auto-classified.",
    )
    config = serializers.JSONField(
        required=False,
        help_text="Optional JSON configuration for the job (stored in job.config).",
    )


class StandardResponseSerializer(serializers.Serializer):
    """Standardized API response wrapper used by endpoints."""

    success = serializers.BooleanField(help_text="True if the request was successful.")
    job_id = serializers.IntegerField(required=False, help_text="Ingestion job id when applicable.")
    status = serializers.CharField(required=False, help_text="Current status string.")
    counts = serializers.DictField(
        child=serializers.IntegerField(),
        required=False,
        help_text="Counts such as total, processed, succeeded, failed.",
    )
    error = serializers.CharField(required=False, allow_blank=True, help_text="Error message if any.")
    detail = serializers.JSONField(required=False, help_text="Additional details or metadata.")
