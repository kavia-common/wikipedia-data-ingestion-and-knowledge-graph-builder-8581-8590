from django.urls import path

from .views import (
    health,
    upload_csv,
    single_ingest,
    job_status,
    job_items,
)

urlpatterns = [
    path("health/", health, name="Health"),
    # Ingestion endpoints
    path("ingest/upload-csv/", upload_csv, name="ingest-upload-csv"),
    path("ingest/single/", single_ingest, name="ingest-single"),
    path("ingest/jobs/<int:job_id>/", job_status, name="ingest-job-status"),
    path("ingest/jobs/<int:job_id>/items/", job_items, name="ingest-job-items"),
]
