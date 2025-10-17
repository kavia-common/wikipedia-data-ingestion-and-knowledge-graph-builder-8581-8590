from __future__ import annotations

"""
Background task handling for ingestion jobs.

This module provides a process-wide ThreadPoolExecutor (lazy initialized) for
running ingestion pipelines in the background. It exposes a public function
submit_ingestion_job that wraps pipeline_orchestrator.run_job_pipeline in a
Future. It supports a synchronous fallback using the USE_SYNC_INGEST env flag.

Env variables:
- MAX_WORKERS: Number of threads in the pool (default 4)
- USE_SYNC_INGEST: If "true"/"1", disables background execution and runs sync.

Design:
- Lazy initialization to avoid issues in tests and management commands.
- Thread-safe: per-task database updates are already atomic in the orchestrator.
- Safe shutdown is naturally handled by process exit; pool is intentionally
  lazy and not created at import time to avoid forking issues in dev servers.
"""

import atexit
import os
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Optional, Tuple

from django.db import connection  # to ensure connections are closed after thread tasks
from api.models import IngestionJob
from api.services.pipeline_orchestrator import OrchestratorResult, run_job_pipeline
from api.utils.logging import get_logger

logger = get_logger(__name__)

_EXECUTOR: Optional[ThreadPoolExecutor] = None


def _get_max_workers() -> int:
    try:
        return int(os.environ.get("MAX_WORKERS", "4") or "4")
    except ValueError:
        return 4


def _use_sync_ingest() -> bool:
    val = (os.environ.get("USE_SYNC_INGEST", "") or "").strip().lower()
    return val in {"1", "true", "yes", "on"}


def _ensure_executor() -> Optional[ThreadPoolExecutor]:
    """
    Lazy-initialize the global executor. Returns None if sync mode is enabled.
    """
    global _EXECUTOR
    if _use_sync_ingest():
        return None
    if _EXECUTOR is None:
        max_workers = max(1, _get_max_workers())
        logger.info("Initializing ThreadPoolExecutor", extra={"context": {"max_workers": max_workers}})
        _EXECUTOR = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="ingest")
        # Register an atexit hook to attempt a graceful shutdown
        atexit.register(_shutdown_executor)
    return _EXECUTOR


def _shutdown_executor():
    """
    Attempt a graceful shutdown of the executor at process exit.
    """
    global _EXECUTOR
    if _EXECUTOR is not None:
        try:
            logger.info("Shutting down ThreadPoolExecutor...", extra={"context": {}})
            _EXECUTOR.shutdown(wait=False, cancel_futures=False)
        except Exception as e:
            logger.warning("Error during executor shutdown", extra={"context": {"error": str(e)}})
        finally:
            _EXECUTOR = None


def _run_pipeline_closing_connection(job_id: int) -> OrchestratorResult:
    """
    Run pipeline by job_id and ensure DB connections in this thread are closed
    after processing to avoid connection leakage in thread pools.
    """
    try:
        job = IngestionJob.objects.get(pk=job_id)
        return run_job_pipeline(job)
    finally:
        # Ensure the thread's DB connection is closed
        try:
            connection.close()
        except Exception as e:
            logger.debug("Error closing DB connection in worker thread: %s", e)


# PUBLIC_INTERFACE
def submit_ingestion_job(job: IngestionJob) -> Tuple[Optional[Future], str]:
    """
    Submit an ingestion job to run in background (if enabled) or synchronously.

    Returns:
        (future, mode)
        - future: concurrent.futures.Future when running async, or None if sync.
        - mode: "async" when submitted to executor, "sync" when run inline.

    Behavior:
    - If USE_SYNC_INGEST=true, runs run_job_pipeline(job) synchronously and returns (None, "sync").
    - Otherwise, submits to ThreadPoolExecutor, returns (Future, "async").
    """
    if _use_sync_ingest():
        logger.info(
            "USE_SYNC_INGEST enabled; running job synchronously.",
            extra={"context": {"job_id": job.pk}},
        )
        # Run synchronously in the request thread
        run_job_pipeline(job)
        return None, "sync"

    executor = _ensure_executor()
    if executor is None:
        # This path should not hit because _use_sync_ingest returns above,
        # but keep a safe fallback.
        logger.info(
            "Executor unavailable; running job synchronously (fallback).",
            extra={"context": {"job_id": job.pk}},
        )
        run_job_pipeline(job)
        return None, "sync"

    # Use ID to avoid capturing potentially stale model instances
    future = executor.submit(_run_pipeline_closing_connection, job.pk)
    return future, "async"
