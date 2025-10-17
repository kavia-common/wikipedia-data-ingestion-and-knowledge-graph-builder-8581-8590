"""
Neo4j writer service.

Connects to Neo4j with environment credentials and writes nodes/relationships
for Article and Chunk entities using MERGE-based idempotent operations.

Schema:
- (:Article {title, url})
- (:Chunk {id, index, text_length, embedding_dim})
- (Article)-[:HAS_CHUNK]->(Chunk)

Constraints/Indexes (created if absent):
- CONSTRAINT article_title_unique IF NOT EXISTS FOR (a:Article) REQUIRE a.title IS UNIQUE
- INDEX chunk_id IF NOT EXISTS FOR (c:Chunk) ON (c.id)

Notes:
- Embeddings are optionally stored on Chunk nodes as a list<float>.
  Beware of storage size; can be disabled by passing store_embeddings=False.
- All network operations are encapsulated for easy mocking in tests.
"""

from __future__ import annotations

import hashlib
from typing import Dict, List, Optional, Sequence, Tuple

from neo4j import GraphDatabase, Driver, Session

from api.utils.env import get_neo4j_password, get_neo4j_uri, get_neo4j_user
from api.utils.logging import get_logger
from api.exceptions import Neo4jWriteError
from api.utils.context import build_log_ctx

logger = get_logger(__name__)


def _hash_chunk_id(article_title: str, index: int, text: str) -> str:
    h = hashlib.sha256()
    h.update((article_title or "").encode("utf-8"))
    h.update(b"|")
    h.update(str(index).encode("utf-8"))
    h.update(b"|")
    # include short text sample to avoid accidental collisions
    h.update((text[:128] or "").encode("utf-8"))
    return h.hexdigest()


class Neo4jWriter:
    """Thin wrapper for Neo4j write operations."""
    def __init__(self, uri: Optional[str] = None, user: Optional[str] = None, password: Optional[str] = None):
        self._uri = uri or get_neo4j_uri()
        self._user = user or get_neo4j_user()
        self._password = password or get_neo4j_password()
        self._driver: Optional[Driver] = None

    def _get_driver(self) -> Driver:
        if self._driver is None:
            if not (self._uri and self._user and self._password):
                logger.error(
                    "Neo4j credentials are missing",
                    extra=build_log_ctx(extra={"uri": bool(self._uri), "user": bool(self._user)}),
                )
                raise Neo4jWriteError("Neo4j credentials are not configured via environment variables.")
            try:
                self._driver = GraphDatabase.driver(self._uri, auth=(self._user, self._password))
            except Exception as e:
                logger.error(
                    "Failed to create Neo4j driver",
                    extra=build_log_ctx(extra={"uri": self._uri, "error": str(e)}),
                )
                raise Neo4jWriteError(f"Failed to create Neo4j driver: {e}") from e
        return self._driver

    def close(self):
        if self._driver:
            self._driver.close()
            self._driver = None

    def _ensure_schema(self, session: Session):
        session.run(
            "CREATE CONSTRAINT article_title_unique IF NOT EXISTS "
            "FOR (a:Article) REQUIRE a.title IS UNIQUE"
        )
        session.run(
            "CREATE INDEX chunk_id IF NOT EXISTS FOR (c:Chunk) ON (c.id)"
        )

    # PUBLIC_INTERFACE
    def write_article_with_chunks(
        self,
        title: str,
        url: str,
        chunks: Sequence[Dict[str, object]],
        embeddings: Optional[Sequence[Sequence[float]]] = None,
        store_embeddings: bool = True,
    ) -> Tuple[int, int]:
        """
        Write or merge an Article node with its Chunk nodes and relationships.

        Args:
            title: Article title.
            url: Canonical URL.
            chunks: Sequence of dicts produced by chunking service: {"text": str, "metadata": {...}}.
            embeddings: Optional list of embeddings aligned with chunks.
            store_embeddings: Whether to store the embeddings on Chunk nodes.

        Returns:
            Tuple (article_count, chunk_created_or_merged_count)
        """
        try:
            driver = self._get_driver()
            with driver.session() as session:
                try:
                    self._ensure_schema(session)
                except Exception as e:
                    logger.error(
                        "Failed ensuring Neo4j schema",
                        extra=build_log_ctx(extra={"title": title, "url": url, "error": str(e)}),
                    )
                    raise Neo4jWriteError(f"Failed ensuring Neo4j schema: {e}") from e

                # MERGE the article first
                try:
                    session.run(
                        """
                        MERGE (a:Article {title: $title})
                        ON CREATE SET a.url = $url
                        ON MATCH SET a.url = coalesce(a.url, $url)
                        """,
                        {"title": title, "url": url},
                    )
                except Exception as e:
                    logger.error(
                        "Failed merging article",
                        extra=build_log_ctx(extra={"title": title, "url": url, "error": str(e)}),
                    )
                    raise Neo4jWriteError(f"Failed merging article {title}: {e}") from e

                # Write chunks
                created_count = 0
                for idx, ch in enumerate(chunks):
                    text = str(ch.get("text", "") or "")
                    meta = ch.get("metadata") or {}
                    chunk_id = _hash_chunk_id(title, idx, text)
                    emb: Optional[List[float]] = None
                    if embeddings and idx < len(embeddings):
                        emb = list(map(float, embeddings[idx]))

                    params = {
                        "title": title,
                        "chunk_id": chunk_id,
                        "index": int(idx),
                        "text": text,
                        "text_length": int(len(text)),
                        "meta": dict(meta),
                        "embedding": emb if (store_embeddings and emb is not None) else None,
                        "embedding_dim": int(len(emb)) if (store_embeddings and emb is not None) else None,
                    }

                    try:
                        session.run(
                            """
                            MATCH (a:Article {title: $title})
                            MERGE (c:Chunk {id: $chunk_id})
                            ON CREATE SET
                                c.index = $index,
                                c.text = $text,
                                c.text_length = $text_length,
                                c.meta = $meta,
                                c.embedding = $embedding,
                                c.embedding_dim = $embedding_dim
                            ON MATCH SET
                                c.text = $text,
                                c.text_length = $text_length,
                                c.meta = $meta,
                                c.embedding = CASE WHEN $embedding IS NULL THEN c.embedding ELSE $embedding END,
                                c.embedding_dim = CASE WHEN $embedding_dim IS NULL THEN c.embedding_dim ELSE $embedding_dim END
                            MERGE (a)-[:HAS_CHUNK]->(c)
                            """,
                            params,
                        )
                    except Exception as e:
                        logger.error(
                            "Failed writing chunk",
                            extra=build_log_ctx(
                                extra={"title": title, "chunk_index": idx, "chunk_id": chunk_id, "error": str(e)}
                            ),
                        )
                        raise Neo4jWriteError(f"Failed writing chunk {idx} for {title}: {e}") from e
                    created_count += 1

                return 1, created_count
        except Neo4jWriteError:
            # Already logged with context; just re-raise
            raise
        except Exception as e:
            logger.error("Unexpected Neo4j write error", extra=build_log_ctx(extra={"error": str(e)}))
            raise Neo4jWriteError(f"Unexpected Neo4j error: {e}") from e
