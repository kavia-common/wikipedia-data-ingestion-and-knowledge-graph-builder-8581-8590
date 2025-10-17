"""
Embeddings and simple RAG helpers.

Supports local sentence-transformers by default and optional OpenAI embeddings
when EMBEDDINGS_PROVIDER=openai and OPENAI_API_KEY is set.

This module only provides embedding functions and a very light-weight retrieval
utility hook; the full vector store is not persisted here since the primary
storage is Neo4j for the knowledge graph. Embeddings are returned to be stored
alongside chunks when writing to Neo4j if desired.

Environment variables:
- EMBEDDINGS_PROVIDER: "sentence-transformers" (default) or "openai"
- OPENAI_API_KEY: required for OpenAI provider
"""

from __future__ import annotations

from typing import Iterable, List

import numpy as np

from api.utils.env import get_embeddings_provider, get_openai_api_key
from api.utils.logging import get_logger

logger = get_logger(__name__)

# Delay heavy imports until needed for easier testing and to avoid issues if not used.
_sentence_model = None
_openai_client = None


def _ensure_sentence_transformers():
    global _sentence_model
    if _sentence_model is None:
        from sentence_transformers import SentenceTransformer

        # Using a small, widely available model by default for local embedding
        # This can be overridden by setting SENTENCE_TRANSFORMERS_MODEL env if desired.
        import os

        model_name = os.environ.get("SENTENCE_TRANSFORMERS_MODEL", "all-MiniLM-L6-v2")
        _sentence_model = SentenceTransformer(model_name)


def _ensure_openai():
    global _openai_client
    if _openai_client is None:
        # Use OpenAI client from openai package if available in environment
        try:
            from openai import OpenAI  # type: ignore
        except Exception as e:
            raise RuntimeError("OpenAI client not available. Install openai package.") from e

        key = get_openai_api_key()
        if not key:
            raise RuntimeError("OPENAI_API_KEY not set but EMBEDDINGS_PROVIDER=openai")
        _openai_client = OpenAI(api_key=key)


# PUBLIC_INTERFACE
def embed_texts(texts: Iterable[str]) -> List[List[float]]:
    """
    Compute embeddings for a list of texts using the configured provider.

    Returns:
        List of embedding vectors (list of floats).
    """
    provider = get_embeddings_provider().lower()
    texts_list = [t or "" for t in texts]

    if provider in ("openai", "openai-embeddings"):
        _ensure_openai()
        # Default model for embeddings; can be overridden via OPENAI_EMBEDDINGS_MODEL
        import os

        model_name = os.environ.get("OPENAI_EMBEDDINGS_MODEL", "text-embedding-3-small")
        # Note: Avoid network in tests by mocking this function.
        resp = _openai_client.embeddings.create(model=model_name, input=texts_list)
        vectors = [d.embedding for d in resp.data]
        return [list(map(float, v)) for v in vectors]

    # Default: sentence-transformers local
    _ensure_sentence_transformers()
    emb = _sentence_model.encode(texts_list, convert_to_numpy=True, normalize_embeddings=True)
    if isinstance(emb, np.ndarray):
        return emb.astype(float).tolist()
    return [[float(x) for x in row] for row in emb]


# PUBLIC_INTERFACE
def embed_text(text: str) -> List[float]:
    """Convenience wrapper to embed a single text."""
    return embed_texts([text])[0]
