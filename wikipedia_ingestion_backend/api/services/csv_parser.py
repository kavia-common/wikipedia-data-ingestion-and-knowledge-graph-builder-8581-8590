"""
CSV Parser service.

Reads a CSV (bytes or text path-like content passed in-memory by caller),
extracts a list of inputs (topics or links). The column used can be specified,
otherwise the first column is used by default.

Design notes:
- Avoids direct file I/O; expects a file-like object or raw bytes provided by callers (e.g., uploaded file).
- Easy to mock in tests: primary entrypoint accepts CSV string content.
"""

from __future__ import annotations

import csv
import io
from typing import List, Optional, Tuple

from api.exceptions import CSVFormatError
from api.utils.logging import get_logger
from api.utils.context import build_log_ctx

logger = get_logger(__name__)


# PUBLIC_INTERFACE
def parse_csv_content(
    csv_bytes: bytes,
    column_name: Optional[str] = None,
    has_header: bool = True,
    encoding: str = "utf-8",
) -> List[str]:
    """
    Parse CSV bytes and return list of string values from the specified column
    (or first column if not provided).

    Args:
        csv_bytes: Raw CSV content as bytes (e.g., from Django UploadedFile.read()).
        column_name: Optional column name to extract; if not present, falls back to first column.
        has_header: Whether the CSV has a header row.
        encoding: Encoding for decoding bytes to text.

    Returns:
        List of non-empty strings extracted from the column.
    """
    try:
        text = csv_bytes.decode(encoding, errors="replace")
    except Exception as e:
        logger.error("Failed decoding CSV bytes", extra=build_log_ctx(extra={"error": str(e)}))
        raise CSVFormatError(f"Unable to decode CSV bytes as {encoding}: {e}") from e

    f = io.StringIO(text, newline="")
    try:
        reader = csv.reader(f)
        rows = list(reader)
    except Exception as e:
        logger.error("Failed parsing CSV content", extra=build_log_ctx(extra={"error": str(e)}))
        raise CSVFormatError(f"Unable to parse CSV: {e}") from e

    if not rows:
        # No rows is considered valid but empty
        return []

    start_index = 0
    col_idx = 0

    if has_header:
        header = rows[0]
        start_index = 1
        if column_name and header:
            try:
                col_idx = header.index(column_name)
            except ValueError:
                # Fallback to first column if the specified column does not exist
                logger.info(
                    "Column name not found in header; falling back to first column",
                    extra=build_log_ctx(extra={"column_name": column_name, "header": header}),
                )
                col_idx = 0
    # Else: no header, use first column (col_idx = 0)

    values: List[str] = []
    for r in rows[start_index:]:
        if not r:
            continue
        if col_idx >= len(r):
            continue
        val = (r[col_idx] or "").strip()
        if val:
            values.append(val)
    return values


# PUBLIC_INTERFACE
def classify_source(value: str) -> Tuple[str, str]:
    """
    Classify the given value as a TOPIC or LINK.

    Simple heuristic:
    - If value starts with http(s):// and contains 'wikipedia.org', classify as LINK.
    - Otherwise, treat as TOPIC.

    Returns:
        (source_type, normalized_value)
        where source_type in {"TOPIC", "LINK"}.
    """
    v = (value or "").strip()
    lower = v.lower()
    if lower.startswith("http://") or lower.startswith("https://"):
        if "wikipedia.org" in lower:
            return "LINK", v
        # Non-wikipedia links could still be treated as LINK to allow custom fetchers later
        return "LINK", v
    return "TOPIC", v
