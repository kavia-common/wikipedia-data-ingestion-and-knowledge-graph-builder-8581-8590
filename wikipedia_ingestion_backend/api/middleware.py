from __future__ import annotations

"""
Middleware to attach a request_id to each request.

- Reads incoming header X-Request-ID if present; otherwise generates a UUID4.
- Exposes request.request_id for downstream logging and propagation.
"""

import uuid
from typing import Callable

from django.utils.deprecation import MiddlewareMixin

from .utils.context import REQUEST_ID_META_KEY


class RequestIDMiddleware(MiddlewareMixin):
    """
    Attaches request_id to the request object for correlation in logs.

    The request_id is taken from header X-Request-ID or generated if missing.
    """

    def process_request(self, request):
        header_key = "HTTP_X_REQUEST_ID"
        incoming = request.META.get(header_key)
        rid = incoming or str(uuid.uuid4())
        setattr(request, REQUEST_ID_META_KEY, rid)
        # Also stash in META for convenience
        request.META[REQUEST_ID_META_KEY] = rid

    def __call__(self, request, get_response: Callable = None):
        # Support Django middleware calling convention
        self.process_request(request)
        response = self.get_response(request)
        # Expose the request-id back on the response header for clients
        rid = getattr(request, REQUEST_ID_META_KEY, None)
        if rid:
            response["X-Request-ID"] = rid
        return response
