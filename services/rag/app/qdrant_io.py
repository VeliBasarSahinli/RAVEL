"""Qdrant client wrapper for the rag_knowledge_base collection.

Payload schema (CLAUDE.md uyumlu):
    chunk_id, content_type, grade_level, subject, file_name,
    test_no, question_number, taxonomic_level, answer_key, has_image,
    text_content
"""
import hashlib
import logging
from typing import Any, Optional

from qdrant_client import AsyncQdrantClient
from qdrant_client.http.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from .schemas import ParsedChunk, RetrievedChunk

logger = logging.getLogger(__name__)


def _stable_id(chunk_id: str) -> str:
    """Qdrant id alanı UUID veya integer olmalı; chunk_id'mizi MD5'e
    bağlayıp UUID-string'e çeviriyoruz (deterministik, idempotent)."""
    h = hashlib.md5(chunk_id.encode("utf-8")).hexdigest()
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


class QdrantIO:
    def __init__(self, url: str, collection: str, vector_dim: int):
        self.url = url
        self.collection = collection
        self.vector_dim = vector_dim
        self._client: Optional[AsyncQdrantClient] = None

    @property
    def client(self) -> AsyncQdrantClient:
        if self._client is None:
            raise RuntimeError("QdrantIO not started")
        return self._client

    async def start(self) -> None:
        self._client = AsyncQdrantClient(url=self.url)
        await self._ensure_collection()

    async def stop(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None

    async def _ensure_collection(self) -> None:
        existing = await self._client.get_collections()
        names = {c.name for c in existing.collections}
        if self.collection in names:
            logger.info("Qdrant collection '%s' already exists", self.collection)
            return
        await self._client.create_collection(
            collection_name=self.collection,
            vectors_config=VectorParams(size=self.vector_dim, distance=Distance.COSINE),
            on_disk_payload=True,
        )
        logger.info("Qdrant collection '%s' created (dim=%d, cosine)",
                    self.collection, self.vector_dim)

    # ─── Mutations ──────────────────────────────────────────────────

    async def upsert_chunks(
        self,
        chunks: list[ParsedChunk],
        vectors: list[list[float]],
    ) -> int:
        if len(chunks) != len(vectors):
            raise ValueError(f"chunks ({len(chunks)}) vs vectors ({len(vectors)}) length mismatch")
        if not chunks:
            return 0
        points = [
            PointStruct(
                id=_stable_id(chunk.chunk_id),
                vector=vec,
                payload={
                    "chunk_id": chunk.chunk_id,
                    "text_content": chunk.text_content,
                    "has_image": chunk.has_image,
                    **chunk.metadata,
                },
            )
            for chunk, vec in zip(chunks, vectors)
        ]
        await self._client.upsert(collection_name=self.collection, points=points, wait=True)
        return len(points)

    async def delete_by_source(self, file_name: str) -> int:
        """Idempotent re-ingestion: bir dosyaya ait tüm chunk'ları sil."""
        flt = Filter(must=[FieldCondition(key="file_name", match=MatchValue(value=file_name))])
        # Önce kaç tane vardı (audit için)
        count = await self._client.count(collection_name=self.collection, count_filter=flt, exact=True)
        if count.count == 0:
            return 0
        await self._client.delete(collection_name=self.collection, points_selector=flt, wait=True)
        logger.info("Qdrant: deleted %d points where file_name=%s", count.count, file_name)
        return count.count

    # ─── Queries ────────────────────────────────────────────────────

    async def search(
        self,
        query_vector: list[float],
        filters: dict[str, Any],
        top_k: int,
        score_threshold: float,
    ) -> list[RetrievedChunk]:
        must = [
            FieldCondition(key=k, match=MatchValue(value=v))
            for k, v in filters.items()
            if v is not None
        ]
        qfilter = Filter(must=must) if must else None
        hits = await self._client.search(
            collection_name=self.collection,
            query_vector=query_vector,
            query_filter=qfilter,
            limit=top_k,
            score_threshold=score_threshold,
        )
        return [
            RetrievedChunk(
                chunk_id=str(hit.payload.get("chunk_id", hit.id)),
                text=str(hit.payload.get("text_content", "")),
                score=float(hit.score),
                metadata={k: v for k, v in hit.payload.items() if k != "text_content"},
            )
            for hit in hits
        ]

    async def get_collection_stats(self) -> dict[str, Any]:
        info = await self._client.get_collection(self.collection)
        return {
            "name": self.collection,
            "vectors_count": info.points_count or 0,
            "vector_dim": self.vector_dim,
        }

    async def count_by_payload(self, key: str) -> dict[str, int]:
        """Group-by: bir payload alanına göre count.

        Qdrant'ın native group-by'ı yok; küçük koleksiyonlar için scroll
        ile sayım yeterli (admin/stats endpoint'i için).
        """
        result: dict[str, int] = {}
        offset = None
        while True:
            batch, next_offset = await self._client.scroll(
                collection_name=self.collection,
                limit=512,
                offset=offset,
                with_payload=[key],
                with_vectors=False,
            )
            for point in batch:
                v = point.payload.get(key) if point.payload else None
                key_str = str(v) if v is not None else "null"
                result[key_str] = result.get(key_str, 0) + 1
            if next_offset is None:
                break
            offset = next_offset
        return result
