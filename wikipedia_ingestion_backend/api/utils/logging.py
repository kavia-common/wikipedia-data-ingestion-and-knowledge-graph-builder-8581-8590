"""
Logging utilities for service modules.

These helpers wrap Python's logging to provide consistent namespacing.
"""

from __future__ import annotations

import logging


# PUBLIC_INTERFACE
def get_logger(name: str) -> logging.Logger:
    """Return a module-specific logger."""
    return logging.getLogger(name)
