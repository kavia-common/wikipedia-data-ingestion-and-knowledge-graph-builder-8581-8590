from __future__ import annotations

from typing import List

from django.shortcuts import get_object_or_404
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.response import Response

from .models import IngestionItem, IngestionJob
from .serializers import (
    IngestionItemSerializer,
    IngestionJobSerializer,
    SingleIngestRequestSerializer,
    StandardResponseSerializer,
    UploadCSVRequestSerializer,
)
from .services.csv_parser import classify_source, parse_csv_content
from .services.pipeline_orchestrator import OrchestratorResult
from .tasks import submit_ingestion_job
from .exceptions import CSVFormatError
from .utils.logging import get_logger
from .utils.context import build_log_ctx

logger = get_logger(__name__)


# PUBLIC_INTERFACE
@api_view(["GET"])
def health(request):
    """
    Simple health endpoint.

    Returns:
        200 OK with a small JSON body indicating service availability.
    """
    return Response({"message": "Server is up!"})


# PUBLIC_INTERFACE
@swagger_auto_schema(
    method="post",
    operation_id="upload_csv_ingest",
    operation_summary="Upload CSV for ingestion",
    operation_description="Upload a CSV file with topics or Wikipedia links to create a job and start processing.",
    request_body=UploadCSVRequestSerializer,
    responses={
        200: openapi.Response(
            description="Ingestion job created and processing started.",
            schema=StandardResponseSerializer,
        ),
        400: "Invalid input",
    },
    tags=["ingestion"],
)
@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser])
def upload_csv(request):
    """
    POST /api/ingest/upload-csv/

    Accepts a multipart/form-data payload with a CSV file and optional parameters,
    creates an IngestionJob and child IngestionItems, executes the pipeline,
    and returns a standardized JSON response.
    """
    serializer = UploadCSVRequestSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(
            {"success": False, "error": serializer.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )

    csv_file = serializer.validated_data["csv_file"]
    column_name = serializer.validated_data.get("column_name") or None
    has_header = serializer.validated_data.get("has_header", True)
    config = serializer.validated_data.get("config") or None

    try:
        inputs = parse_csv_content(csv_file.read(), column_name=column_name, has_header=has_header)
    except CSVFormatError as e:
        logger.warning(
            "CSV parsing failed",
            extra=build_log_ctx(request, extra={"error": str(e)}),
        )
        return Response(
            {"success": False, "error": f"Failed to parse CSV: {e}"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    except Exception as e:
        logger.exception("Unexpected error parsing CSV", extra=build_log_ctx(request))
        return Response(
            {"success": False, "error": f"Unexpected error parsing CSV: {e}"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if not inputs:
        return Response(
            {"success": False, "error": "CSV contained no usable values."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    job = IngestionJob.objects.create(
        status=IngestionJob.Status.PENDING,
        total_items=len(inputs),
        processed_items=0,
        config=config,
    )

    items: List[IngestionItem] = []
    for v in inputs:
        src_type, norm_val = classify_source(v)
        items.append(
            IngestionItem(
                job=job,
                input_value=norm_val,
                source_type=src_type,
                status=IngestionItem.Status.PENDING,
            )
        )
    IngestionItem.objects.bulk_create(items, batch_size=500)

    logger.info(
        "Created ingestion job",
        extra=build_log_ctx(request, job_id=job.id, extra={"items": len(inputs)}),
    )

    # Submit to background executor (or run synchronously if configured)
    future, mode = submit_ingestion_job(job)

    if mode == "async":
        logger.info(
            "Submitted job for background processing",
            extra=build_log_ctx(request, job_id=job.id),
        )
        # Immediately return pending status; processing happens in background
        data = {
            "success": True,
            "job_id": job.id,
            "status": job.status,  # should be PENDING initially; orchestrator will update to RUNNING shortly
            "counts": {
                "total": job.total_items,
                "processed": job.processed_items,
                "succeeded": 0,
                "failed": 0,
            },
            "detail": {"message": "Job submitted for background processing."},
        }
        return Response(data, status=status.HTTP_200_OK)

    # Sync path: return final result
    # For sync mode, orchestrator has fully processed the job by now
    result: OrchestratorResult = OrchestratorResult(
        total=job.total_items,
        succeeded=job.items.filter(status=IngestionItem.Status.SUCCESS).count(),
        failed=job.items.filter(status=IngestionItem.Status.FAILED).count(),
        details=[],
    )
    data = {
        "success": True,
        "job_id": job.id,
        "status": job.status,
        "counts": {
            "total": result.total,
            "processed": job.processed_items,
            "succeeded": result.succeeded,
            "failed": result.failed,
        },
        "detail": {"message": "Job ran synchronously (USE_SYNC_INGEST)."},
    }
    return Response(data, status=status.HTTP_200_OK)


# PUBLIC_INTERFACE
@swagger_auto_schema(
    method="post",
    operation_id="single_value_ingest",
    operation_summary="Ingest a single topic or link",
    operation_description="Create a job for a single topic or Wikipedia URL and process immediately.",
    request_body=SingleIngestRequestSerializer,
    responses={
        200: openapi.Response(
            description="Single ingest job created and processed.",
            schema=StandardResponseSerializer,
        ),
        400: "Invalid input",
    },
    tags=["ingestion"],
)
@api_view(["POST"])
@parser_classes([JSONParser, FormParser])
def single_ingest(request):
    """
    POST /api/ingest/single/

    Accepts JSON with a single 'value' and optional 'source_type' and 'config'.
    Creates a job and item, executes the pipeline, and returns standardized JSON.
    """
    serializer = SingleIngestRequestSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(
            {"success": False, "error": serializer.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )

    value = (serializer.validated_data["value"] or "").strip()
    if not value:
        return Response(
            {"success": False, "error": "Value must be a non-empty string."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    provided_type = serializer.validated_data.get("source_type")
    config = serializer.validated_data.get("config") or None

    if provided_type:
        source_type = provided_type
        normalized_value = value
    else:
        source_type, normalized_value = classify_source(value)

    job = IngestionJob.objects.create(
        status=IngestionJob.Status.PENDING,
        total_items=1,
        processed_items=0,
        config=config,
    )
    IngestionItem.objects.create(
        job=job,
        input_value=normalized_value,
        source_type=source_type,
        status=IngestionItem.Status.PENDING,
    )

    logger.info(
        "Created single ingestion job",
        extra=build_log_ctx(request, job_id=job.id, extra={"source_type": source_type}),
    )

    # Submit to background executor (or run synchronously)
    future, mode = submit_ingestion_job(job)

    if mode == "async":
        logger.info(
            "Submitted single job for background processing",
            extra=build_log_ctx(request, job_id=job.id),
        )
        data = {
            "success": True,
            "job_id": job.id,
            "status": job.status,
            "counts": {
                "total": job.total_items,
                "processed": job.processed_items,
                "succeeded": 0,
                "failed": 0,
            },
            "detail": {"message": "Job submitted for background processing."},
        }
        return Response(data, status=status.HTTP_200_OK)

    # Sync fallback response
    result: OrchestratorResult = OrchestratorResult(
        total=job.total_items,
        succeeded=job.items.filter(status=IngestionItem.Status.SUCCESS).count(),
        failed=job.items.filter(status=IngestionItem.Status.FAILED).count(),
        details=[],
    )
    data = {
        "success": True,
        "job_id": job.id,
        "status": job.status,
        "counts": {
            "total": result.total,
            "processed": job.processed_items,
            "succeeded": result.succeeded,
            "failed": result.failed,
        },
        "detail": {"message": "Job ran synchronously (USE_SYNC_INGEST)."},
    }
    return Response(data, status=status.HTTP_200_OK)


# PUBLIC_INTERFACE
@swagger_auto_schema(
    method="get",
    operation_id="get_job_status",
    operation_summary="Get ingestion job status",
    operation_description="Retrieve an ingestion job's current status and counts.",
    manual_parameters=[
        openapi.Parameter(
            "job_id", openapi.IN_PATH, description="Ingestion job id", type=openapi.TYPE_INTEGER, required=True
        )
    ],
    responses={200: openapi.Response(description="Job status", schema=IngestionJobSerializer)},
    tags=["ingestion"],
)
@api_view(["GET"])
def job_status(request, job_id: int):
    """
    GET /api/ingest/jobs/{job_id}/

    Returns serialized job details including counts.
    """
    job = get_object_or_404(IngestionJob, pk=job_id)
    data = IngestionJobSerializer(job).data
    # Add a counts helper object for standardized response
    counts = {
        "total": job.total_items,
        "processed": job.processed_items,
        "succeeded": job.items.filter(status=IngestionItem.Status.SUCCESS).count(),
        "failed": job.items.filter(status=IngestionItem.Status.FAILED).count(),
    }
    return Response(
        {
            "success": True,
            "job_id": job.id,
            "status": job.status,
            "counts": counts,
            "detail": data,
        },
        status=status.HTTP_200_OK,
    )


# PUBLIC_INTERFACE
@swagger_auto_schema(
    method="get",
    operation_id="get_job_items",
    operation_summary="List items for a job",
    operation_description="Retrieve all items belonging to a job with their statuses.",
    manual_parameters=[
        openapi.Parameter(
            "job_id", openapi.IN_PATH, description="Ingestion job id", type=openapi.TYPE_INTEGER, required=True
        )
    ],
    responses={200: openapi.Response(description="List of items", schema=IngestionItemSerializer(many=True))},
    tags=["ingestion"],
)
@api_view(["GET"])
def job_items(request, job_id: int):
    """
    GET /api/ingest/jobs/{job_id}/items/

    Returns serialized list of items for a given job.
    """
    job = get_object_or_404(IngestionJob, pk=job_id)
    items_qs = job.items.all().order_by("-created_at")
    items_data = IngestionItemSerializer(items_qs, many=True).data
    counts = {
        "total": job.total_items,
        "processed": job.processed_items,
        "succeeded": job.items.filter(status=IngestionItem.Status.SUCCESS).count(),
        "failed": job.items.filter(status=IngestionItem.Status.FAILED).count(),
    }
    return Response(
        {
            "success": True,
            "job_id": job.id,
            "status": job.status,
            "counts": counts,
            "detail": items_data,
        },
        status=status.HTTP_200_OK,
    )
