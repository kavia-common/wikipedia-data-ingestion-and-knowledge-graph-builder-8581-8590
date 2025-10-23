from __future__ import annotations

"""
Global DRF exception handler.

Converts unhandled exceptions into standardized JSON responses and ensures
structured logging with request_id and optional job_id context.
"""

from typing import Any, Dict

from django.http import Http404
from django.core.exceptions import PermissionDenied
from rest_framework import status
from rest_framework.views import exception_handler as drf_exception_handler
from rest_framework.response import Response
from rest_framework.exceptions import APIException, ValidationError

from .utils.logging import get_logger
from .utils.context import build_log_ctx

logger = get_logger(__name__)


# PUBLIC_INTERFACE
def custom_exception_handler(exc: Exception, context: Dict[str, Any]):
    """
    Custom DRF exception handler.

    Args:
        exc: The raised exception.
        context: Context dict provided by DRF containing the 'view' and 'request'.

    Returns:
        Response produced by DRF default handler if recognized; otherwise
        a standardized JSON error response with appropriate status code.

    Envelope:
        {
            "success": false,
            "error": "<short message>",
            "detail": <optional structured details dict/list/string>
        }
    """
    # First, let DRF handle known exceptions (ValidationError, APIException, etc.)
    response = drf_exception_handler(exc, context)

    request = context.get("request")
    if response is not None:
        # Known/handled by DRF exceptions: log at warning level with details
        logger.warning(
            "Handled API exception",
            extra=build_log_ctx(request, extra={"status_code": response.status_code}),
        )
        # Ensure standardized envelope with original DRF payload in detail
        detail = response.data
        # Use conventional short error message based on status code class
        default_msg = "Request invalid" if 400 <= response.status_code < 500 else "Server error"
        # Some DRF exceptions include "detail" string; surface it as error when appropriate
        if isinstance(detail, dict) and "detail" in detail and isinstance(detail["detail"], str):
            error_msg = str(detail["detail"])
        else:
            error_msg = default_msg
        payload = {"success": False, "error": error_msg, "detail": detail}
        return Response(payload, status=response.status_code)

    # Unhandled exceptions: decide on status code
    if isinstance(exc, Http404):
        code = status.HTTP_404_NOT_FOUND
        msg = "Not found"
        detail = None
    elif isinstance(exc, PermissionDenied):
        code = status.HTTP_403_FORBIDDEN
        msg = "Permission denied"
        detail = None
    elif isinstance(exc, ValidationError):
        code = status.HTTP_400_BAD_REQUEST
        msg = "Validation error"
        detail = getattr(exc, "detail", None)
    elif isinstance(exc, APIException):
        # Generic DRF APIException (if not handled by default for some reason)
        code = getattr(exc, "status_code", None) or status.HTTP_400_BAD_REQUEST
        msg = str(getattr(exc, "detail", "")) or "API error"
        detail = getattr(exc, "detail", None)
    else:
        # Internal server error for all others
        code = status.HTTP_500_INTERNAL_SERVER_ERROR
        msg = "Internal server error"
        detail = None

    # Log exception with stack trace and structured context
    logger.exception(
        "Unhandled exception in API",
        extra=build_log_ctx(request),
    )

    payload = {"success": False, "error": msg}
    if detail is not None:
        payload["detail"] = detail
    return Response(payload, status=code)
