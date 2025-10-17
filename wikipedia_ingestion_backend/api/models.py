from django.db import models


class IngestionJob(models.Model):
    """
    Represents a CSV ingestion job that may contain multiple items (topics or links).
    Tracks overall progress, status, and optional configuration used during processing.
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        RUNNING = "RUNNING", "Running"
        SUCCESS = "SUCCESS", "Success"
        FAILED = "FAILED", "Failed"

    created_at = models.DateTimeField(auto_now_add=True, help_text="When the job was created")
    updated_at = models.DateTimeField(auto_now=True, help_text="When the job was last updated")
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        help_text="Overall status of the job",
    )
    total_items = models.PositiveIntegerField(default=0, help_text="Total number of items to process")
    processed_items = models.PositiveIntegerField(default=0, help_text="Number of items processed so far")
    error_message = models.TextField(blank=True, null=True, help_text="Details about any job-level error")
    # Django 5+ has native JSONField in django.db.models
    config = models.JSONField(blank=True, null=True, help_text="Optional configuration parameters for the job")

    class Meta:
        app_label = "api"
        ordering = ["-created_at"]
        verbose_name = "Ingestion Job"
        verbose_name_plural = "Ingestion Jobs"

    def __str__(self) -> str:
        """
        Human-readable representation of the job.
        """
        return f"Job #{self.pk} - {self.status} - {self.processed_items}/{self.total_items}"


class IngestionItem(models.Model):
    """
    A single item within an ingestion job. Represents either a 'topic' or a 'link'
    to be processed (e.g., fetched from Wikipedia) and ingested into the knowledge graph.
    """

    class SourceType(models.TextChoices):
        TOPIC = "TOPIC", "Topic"
        LINK = "LINK", "Link"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        RUNNING = "RUNNING", "Running"
        SUCCESS = "SUCCESS", "Success"
        FAILED = "FAILED", "Failed"

    job = models.ForeignKey(
        IngestionJob,
        on_delete=models.CASCADE,
        related_name="items",
        help_text="Parent ingestion job",
    )
    input_value = models.TextField(help_text="Raw input value from CSV (topic string or URL)")
    source_type = models.CharField(
        max_length=10,
        choices=SourceType.choices,
        help_text="Whether the input is a TOPIC or a LINK",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        help_text="Processing status of this item",
    )
    result_page_title = models.CharField(
        max_length=512,
        blank=True,
        null=True,
        help_text="Resolved Wikipedia page title after processing",
    )
    error_message = models.TextField(blank=True, null=True, help_text="Details about any item-level error")
    meta = models.JSONField(blank=True, null=True, help_text="Arbitrary metadata captured during processing")
    created_at = models.DateTimeField(auto_now_add=True, help_text="When the item was created")
    updated_at = models.DateTimeField(auto_now=True, help_text="When the item was last updated")

    class Meta:
        app_label = "api"
        ordering = ["-created_at"]
        verbose_name = "Ingestion Item"
        verbose_name_plural = "Ingestion Items"
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["source_type"]),
        ]

    def __str__(self) -> str:
        """
        Human-readable representation of the item.
        """
        return f"Item #{self.pk} [{self.source_type}] - {self.status}"
