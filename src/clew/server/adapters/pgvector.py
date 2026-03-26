"""
PostgreSQL + pgvector Vector Store Adapter

Implements the VectorStore protocol using PostgreSQL with the pgvector extension.
This enables Clew to work with a single Postgres database for customers who
don't want to run a separate vector database.

Setup:
    CREATE EXTENSION IF NOT EXISTS vector;

    CREATE TABLE code_embeddings (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        content TEXT NOT NULL,
        embedding vector(1536),
        metadata JSONB DEFAULT '{}'::jsonb,
        created_at TIMESTAMP DEFAULT NOW()
    );

    CREATE INDEX ON code_embeddings USING ivfflat (embedding vector_cosine_ops);
"""

import json
import logging
import uuid
from typing import TYPE_CHECKING, Any

from clew.server.config import settings

from .base import CodeMetadata, SearchFilters, SearchResult, VectorStore

logger = logging.getLogger("clew.adapters.pgvector")


class PgVectorStore:
    """
    PostgreSQL + pgvector implementation of VectorStore protocol.

    Requires:
    - PostgreSQL 15+ with pgvector extension
    - asyncpg for async connections

    Environment:
        POSTGRES_URI=postgresql://user:pass@localhost:5432/clew
    """

    def __init__(
        self,
        connection_uri: str,
        table_name: str = "code_embeddings",
        embedding_dimension: int = settings.EMBEDDING_DIMENSION,
    ):
        self.connection_uri = connection_uri
        self.table_name = table_name
        self.embedding_dimension = embedding_dimension
        self._pool = None

    async def _get_pool(self) -> Any:
        """Get or create connection pool."""
        if self._pool is None:
            try:
                import asyncpg  # type: ignore

                self._pool = await asyncpg.create_pool(self.connection_uri, min_size=1, max_size=10)
                logger.info("PgVector connection pool created")
            except ImportError as e:
                raise ImportError("asyncpg is required for PgVectorStore. Install with: pip install asyncpg") from e

        # At this point, self._pool is guaranteed to not be None
        # if the pool creation succeeds. We check for type compliance.
        pool = self._pool
        assert pool is not None, "Pool failed to initialize"
        return pool

    async def search(
        self,
        query_vector: list[float],
        limit: int = 10,
        repo: str | None = None,
        filters: SearchFilters | None = None,
    ) -> list[SearchResult]:
        """
        Search for similar vectors using pgvector's cosine distance.

        Args:
            query_vector: The embedding vector to search with
            limit: Maximum number of results
            repo: Optional repository filter
            filters: Optional additional filters

        Returns:
            List of SearchResult objects, sorted by similarity descending
        """
        pool = await self._get_pool()

        # Convert vector to pgvector format
        vector_str = f"[{','.join(str(v) for v in query_vector)}]"

        # Build query
        query = f"""
            SELECT
                id,
                content,
                metadata,
                1 - (embedding <=> $1::vector) AS score
            FROM {self.table_name}
        """

        params: list[Any] = [vector_str]

        # Add repo filter if provided
        if repo:
            query += " WHERE metadata->>'repo_id' = $2"
            params.append(repo)

        query += f" ORDER BY embedding <=> $1::vector LIMIT {limit}"

        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(query, *params)

            return [
                SearchResult(
                    id=str(row["id"]),
                    score=float(row["score"]),
                    content=row["content"],
                    metadata=dict(row["metadata"]) if row["metadata"] else {},  # type: ignore[arg-type]
                )
                for row in rows
            ]
        except Exception as e:
            logger.error(f"PgVector search failed: {e}", exc_info=True)
            raise RuntimeError("PgVector search failed") from e

    async def upsert(self, id: str, content: str, vector: list[float], metadata: CodeMetadata | None = None) -> None:
        """
        Insert or update a vector in the database.

        Args:
            id: Unique identifier for the document
            content: The text content
            vector: The embedding vector
            metadata: Optional metadata (repo, path, type, etc.)
        """
        pool = await self._get_pool()
        vector_str = f"[{','.join(str(v) for v in vector)}]"

        query = f"""
            INSERT INTO {self.table_name} (id, content, embedding, metadata)
            VALUES ($1, $2, $3::vector, $4::jsonb)
            ON CONFLICT (id) DO UPDATE SET
                content = EXCLUDED.content,
                embedding = EXCLUDED.embedding,
                metadata = EXCLUDED.metadata
        """

        async with pool.acquire() as conn:
            await conn.execute(
                query,
                uuid.UUID(id) if isinstance(id, str) else id,
                content,
                vector_str,
                json.dumps(metadata or {}),
            )

    async def ensure_table(self) -> None:
        """Create the embeddings table if it doesn't exist."""
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            await conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.table_name} (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    content TEXT NOT NULL,
                    embedding vector({self.embedding_dimension}),
                    metadata JSONB DEFAULT '{{}}'::jsonb,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            # Create index if not exists
            await conn.execute(f"""
                CREATE INDEX IF NOT EXISTS {self.table_name}_embedding_idx
                ON {self.table_name}
                USING ivfflat (embedding vector_cosine_ops)
            """)
            logger.info(f"Ensured table {self.table_name} exists")

    async def close(self) -> None:
        """Close the connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None


if TYPE_CHECKING:
    # Type check: ensure PgVectorStore implements VectorStore
    def _check_protocol() -> VectorStore:
        return PgVectorStore(connection_uri="dummy")  # type: ignore


# =============================================================================
# Auto-registration
# =============================================================================


def _register_pgvector():
    """Register PgVector adapter with the registry."""
    import os

    from . import registry

    def factory() -> PgVectorStore:
        postgres_uri = os.getenv("POSTGRES_URI")
        if not postgres_uri:
            raise ValueError("POSTGRES_URI must be set when using pgvector adapter")
        return PgVectorStore(connection_uri=postgres_uri)

    registry.vector_store_registry.register("pgvector", factory)


# Auto-register on module import
try:
    _register_pgvector()
    logger.debug("Registered PgVector adapter")
except Exception as e:
    logger.debug(f"Skipping PgVector auto-registration: {e}")
