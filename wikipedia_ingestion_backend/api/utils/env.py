"""
Environment utilities for the API services.

Provides typed accessors for commonly used environment variables,
with sensible defaults and no hard-coded secrets. Designed to be
imported by services and orchestration modules.
"""

from __future__ import annotations

import os
from typing import Optional


# PUBLIC_INTERFACE
def get_env(name: str, default: Optional[str] = None) -> Optional[str]:
    """Generic safe getter for environment variables."""
    return os.environ.get(name, default)


# PUBLIC_INTERFACE
def get_request_timeout() -> int:
    """Return request timeout in seconds from REQUEST_TIMEOUT environment variable, default 60."""
    try:
        return int(get_env("REQUEST_TIMEOUT", "60") or "60")
    except ValueError:
        return 60


# PUBLIC_INTERFACE
def get_chunk_size() -> int:
    """Return chunk size from RAG_CHUNK_SIZE environment variable, default 1000."""
    try:
        return int(get_env("RAG_CHUNK_SIZE", "1000") or "1000")
    except ValueError:
        return 1000


# PUBLIC_INTERFACE
def get_chunk_overlap() -> int:
    """Return chunk overlap from RAG_CHUNK_OVERLAP environment variable, default 150."""
    try:
        return int(get_env("RAG_CHUNK_OVERLAP", "150") or "150")
    except ValueError:
        return 150


# PUBLIC_INTERFACE
def get_embeddings_provider() -> str:
    """Return embeddings provider string. Defaults to 'sentence-transformers' (local)."""
    return (get_env("EMBEDDINGS_PROVIDER", "") or "").strip() or "sentence-transformers"


# PUBLIC_INTERFACE
def get_openai_api_key() -> str:
    """Return OpenAI API key if configured, else empty string."""
    return get_env("OPENAI_API_KEY", "") or ""


# PUBLIC_INTERFACE
def get_neo4j_uri() -> str:
    """Return Neo4j URI, e.g., bolt://localhost:7687 or neo4j+s://<host>."""
    return get_env("NEO4J_URI", "") or ""


# PUBLIC_INTERFACE
def get_neo4j_user() -> str:
    """Return Neo4j username."""
    return get_env("NEO4J_USER", "") or ""


# PUBLIC_INTERFACE
def get_neo4j_password() -> str:
    """Return Neo4j password."""
    return get_env("NEO4J_PASSWORD", "") or ""
