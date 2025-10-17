"""
Per-request and per-job context utilities.

Provides helpers to get contextual IDs (request_id, job_id) from the current
request (if available) and safe dict builders for logging.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


REQUEST_ID_META_KEY = "request_id"
JOB_ID_META_KEY = "job_id"


# PUBLIC_INTERFACE
def build_log_ctx(request=None, job_id: Optional[int] = None, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Build a structured logging context dict including request_id and job_id if available.

    Args:
        request: Optional Django request object (middleware injects request_id).
        job_id: Optional ingestion job id to include.
        extra: Optional additional context fields.

    Returns:
        Dict[str, Any] suitable for passing as 'extra' to logger.* calls.
    """
    ctx: Dict[str, Any] = {}
    if request is not None:
        rid = getattr(request, REQUEST_ID_META_KEY, None) or getattr(getattr(request, "META", {}), REQUEST_ID_META_KEY, None)
        if rid:
            ctx["request_id"] = rid
    if job_id is not None:
        ctx["job_id"] = job_id
    if extra:
        # Do not overwrite reserved keys
        for k, v in extra.items():
            if k not in ctx:
                ctx[k] = v
    return {"context": ctx}  # use a single key to avoid clashing with logging reserved names
