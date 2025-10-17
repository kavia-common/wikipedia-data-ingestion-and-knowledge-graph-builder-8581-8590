"""
Chunking service.

Uses LangChain text splitters to split large documents into chunks suitable
for embeddings and RAG. Configurable via environment variables for chunk
size and overlap.
"""

from __future__ import annotations

from typing import Dict, List

from langchain.text_splitter import RecursiveCharacterTextSplitter

from api.utils.env import get_chunk_overlap, get_chunk_size


# PUBLIC_INTERFACE
def chunk_text(
    text: str,
    metadata: Dict[str, str],
) -> List[Dict[str, str]]:
    """
    Split the given text into chunks with associated metadata.

    Args:
        text: The full input text to split.
        metadata: Base metadata for all chunks (e.g., page title, URL).

    Returns:
        List of dicts like {"text": <chunk_text>, "metadata": {...}}.
    """
    chunk_size = get_chunk_size()
    chunk_overlap = get_chunk_overlap()

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
        separators=["\n\n", "\n", " ", ""],
    )
    chunks = splitter.split_text(text or "")

    result: List[Dict[str, str]] = []
    for idx, ch in enumerate(chunks):
        meta = dict(metadata or {})
        meta.update({"chunk_index": idx})
        result.append({"text": ch, "metadata": meta})
    return result
