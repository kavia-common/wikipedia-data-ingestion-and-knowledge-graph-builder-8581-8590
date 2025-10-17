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
        return False, "Empty input value"

    page = fetch_wikipedia(value)
    if not page or not page.text:
        return False, "Failed to fetch Wikipedia content"

    base_meta = {"title": page.title, "url": page.url}
    chunks = chunk_text(page.text, metadata=base_meta)

    texts = [c["text"] for c in chunks]
    embeddings = embed_texts(texts)

    writer.write_article_with_chunks(
        title=page.title,
        url=page.url,
        chunks=chunks,
        embeddings=embeddings,
        store_embeddings=True,
    )

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
                logger.exception("Error processing item %s", item.pk)

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

    finally:
        writer.close()

    return OrchestratorResult(total=total, succeeded=succeeded, failed=failed, details=details)
