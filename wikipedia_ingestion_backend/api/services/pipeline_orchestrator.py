"""
Pipeline orchestrator.

Coordinates CSV-derived items through:
- Wikipedia fetch
- Chunking
- Embeddings
- Neo4j write

Also updates Django models IngestionJob and IngestionItem to reflect progress.

Notes:
- All external/network calls are compartmentalized for easy mocking in tests.
- This module should be called by views/commands that have created a job and items.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

from django.db import transaction

from api.models import IngestionItem, IngestionJob
from api.services.wikipedia_client import fetch_wikipedia
from api.services.chunking import chunk_text
from api.services.rag_pipeline import embed_texts
from api.services.neo4j_writer import Neo4jWriter
from api.utils.logging import get_logger
from api.exceptions import FetchError, Neo4jWriteError
from api.utils.context import build_log_ctx

logger = get_logger(__name__)


@dataclass
class OrchestratorResult:
    total: int
    succeeded: int
    failed: int
    details: List[Dict[str, str]]


def _process_single_item(item: IngestionItem, writer: Neo4jWriter) -> Tuple[bool, str]:
    """
    Process a single ingestion item and write to Neo4j.

    Returns:
        (success, message)
    """
    value = (item.input_value or "").strip()
    if not value:
        logger.warning(
            "Empty input value for item",
            extra=build_log_ctx(job_id=item.job_id, extra={"item_id": item.pk}),
        )
        return False, "Empty input value"

    try:
        page = fetch_wikipedia(value)
    except FetchError as e:
        logger.warning(
            "FetchError in Wikipedia fetch",
            extra=build_log_ctx(job_id=item.job_id, extra={"item_id": item.pk, "error": str(e)}),
        )
        return False, str(e)
    except Exception:
        logger.exception(
            "Unexpected exception during fetch",
            extra=build_log_ctx(job_id=item.job_id, extra={"item_id": item.pk}),
        )
        return False, "Unexpected fetch error"

    # Note: fetch_wikipedia now raises on failure; this path is defensive
    if not page or not page.text:
        logger.warning(
            "No content returned from fetch",
            extra=build_log_ctx(job_id=item.job_id, extra={"item_id": item.pk}),
        )
        return False, "Failed to fetch Wikipedia content"

    base_meta = {"title": page.title, "url": page.url}
    chunks = chunk_text(page.text, metadata=base_meta)

    # If no chunks were produced, skip writing to Neo4j gracefully
    if not chunks:
        logger.info(
            "No chunks generated for page; skipping Neo4j write",
            extra=build_log_ctx(job_id=item.job_id, extra={"item_id": item.pk, "title": page.title}),
        )
        return True, page.title

    texts = [c.get("text", "") for c in chunks]
    # Guard against embedding errors causing entire pipeline to fail
    try:
        embeddings = embed_texts(texts) if texts else []
    except Exception:
        logger.exception(
            "Embedding generation failed; proceeding without embeddings",
            extra=build_log_ctx(job_id=item.job_id, extra={"item_id": item.pk, "title": page.title}),
        )
        embeddings = []

    try:
        writer.write_article_with_chunks(
            title=page.title,
            url=page.url,
            chunks=chunks,
            embeddings=embeddings if embeddings else None,
            store_embeddings=bool(embeddings),
        )
    except Neo4jWriteError as e:
        logger.error(
            "Neo4j write error",
            extra=build_log_ctx(job_id=item.job_id, extra={"item_id": item.pk, "error": str(e)}),
        )
        return False, str(e)
    except Exception as e:
        logger.exception(
            "Unexpected exception during Neo4j write",
            extra=build_log_ctx(job_id=item.job_id, extra={"item_id": item.pk}),
        )
        return False, f"Unexpected Neo4j error: {e}"

    return True, page.title


# PUBLIC_INTERFACE
def run_job_pipeline(job: IngestionJob, queryset=None) -> OrchestratorResult:
    """
    Run the pipeline for all items in the job (optionally filtered queryset).

    Args:
        job: IngestionJob instance.
        queryset: Optional custom queryset of IngestionItem; defaults to job.items.all()

    Returns:
        OrchestratorResult summary.
    """
    # Fetch items to process
    items_qs = queryset if queryset is not None else job.items.all()
    items: List[IngestionItem] = list(items_qs)

    total = len(items)
    succeeded = 0
    failed = 0
    details: List[Dict[str, str]] = []

    logger.info(
        "Starting job pipeline",
        extra=build_log_ctx(job_id=job.pk, extra={"items": total}),
    )

    # Update job status to RUNNING
    with transaction.atomic():
        job.status = IngestionJob.Status.RUNNING
        job.total_items = total
        job.processed_items = 0
        job.save(update_fields=["status", "total_items", "processed_items", "updated_at"])

    writer = Neo4jWriter()
    try:
        for item in items:
            with transaction.atomic():
                item.status = IngestionItem.Status.RUNNING
                item.save(update_fields=["status", "updated_at"])

            ok = False
            message = ""
            try:
                ok, message = _process_single_item(item, writer)
            except Exception as e:
                ok = False
                message = f"Exception: {e}"
                logger.exception(
                    "Unhandled error processing item",
                    extra=build_log_ctx(job_id=job.pk, extra={"item_id": item.pk}),
                )

            with transaction.atomic():
                if ok:
                    item.status = IngestionItem.Status.SUCCESS
                    item.result_page_title = message
                    item.error_message = None
                    succeeded += 1
                else:
                    item.status = IngestionItem.Status.FAILED
                    item.error_message = message
                    failed += 1
                item.save(update_fields=["status", "result_page_title", "error_message", "updated_at"])

                job.processed_items += 1
                job.save(update_fields=["processed_items", "updated_at"])

            details.append({
                "item_id": str(item.pk),
                "status": item.status,
                "message": message,
            })

        # Finalize job status
        with transaction.atomic():
            job.status = IngestionJob.Status.SUCCESS if failed == 0 else IngestionJob.Status.FAILED
            job.save(update_fields=["status", "updated_at"])

        logger.info(
            "Finished job pipeline",
            extra=build_log_ctx(job_id=job.pk, extra={"succeeded": succeeded, "failed": failed}),
        )
    finally:
        writer.close()

    return OrchestratorResult(total=total, succeeded=succeeded, failed=failed, details=details)
