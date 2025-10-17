from __future__ import annotations

"""
Centralized exception types for API/services.

These exceptions enable consistent error signaling across parsing, fetching,
and Neo4j writing flows. Views and orchestrators can catch these to map to
standard responses and logs.
"""

# PUBLIC_INTERFACE
class CSVFormatError(ValueError):
    """Raised when the provided CSV content is malformed or does not match expectations."""


# PUBLIC_INTERFACE
class FetchError(RuntimeError):
    """Raised when fetching Wikipedia content fails after retries."""


# PUBLIC_INTERFACE
class Neo4jWriteError(RuntimeError):
    """Raised when writing to Neo4j fails due to connectivity, auth, or query issues."""
