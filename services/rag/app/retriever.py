"""Retriever — iki aşamalı: hybrid filter + vector search → reranking.

CLAUDE.md hibrit arama mantığı:
  - content_type filtresi zorunlu
  - taxonomic_level (yalnızca theory/explanation; question'da uygulanmaz)
  - grade_level + subject (her iki content_type)

Question'da taxonomic_level neden kapalı:
  Bandit'in önerdiği seviyede (örn. B2) chunk yoksa retriever boş döner ve
  öğrenciye içerik gitmez. Sınıf+konu eşleşen tüm sorulardan retrieval
  yapıp, seviye düzeltmesini Bandit'in reward döngüsüne bırakıyoruz.

Reranking: skor eşiği altındakileri at, en iyi N'i döndür. Eğer hiç
sonuç yoksa eşiği gevşeterek tekrar dene (relaxed threshold).
"""
import asyncio
import logging
import time
from typing import Optional

from .config import Settings
from .embedder import Embedder
from .qdrant_io import QdrantIO
from .schemas import (
    ContentRetrievalRequest,
    ContentRetrievalResponse,
    RetrievedChunk,
)

logger = logging.getLogger(__name__)


class Retriever:
    def __init__(self, settings: Settings, embedder: Embedder, qdrant: QdrantIO):
        self.settings = settings
        self.embedder = embedder
        self.qdrant = qdrant

    async def retrieve(self, request: ContentRetrievalRequest) -> ContentRetrievalResponse:
        start = time.perf_counter()
        ct = request.query.content_type

        # Query augmentation — küçük prefix retrieval kalitesini artırıyor
        prefix = "Matematik sorusu: " if ct == "question" else "Konu anlatımı: "
        query_text = prefix + (request.query.context or request.query.subject or "")
        query_text = query_text.strip()
        if not query_text or query_text == prefix.strip():
            # Hiçbir context yoksa bare prefix anlamsız; sadece subject veya
            # hiçbir şey yoksa boş yanıt
            logger.warning("[%s] retrieve called with empty query", request.trace_id)
            return ContentRetrievalResponse(
                correlation_id=request.correlation_id,
                trace_id=request.trace_id,
                chunks=[],
                total_found=0,
            )

        # ── Filter mantığı ────────────────────────────────────────
        # Zorunlu: content_type
        # taxonomic_level: sadece question DEĞİLSE uygulanır
        #   (question retrieval boş dönmesin → seviye ayarı Bandit'te)
        # subject: değer gelirse uygulanır
        # grade_level filter KALDIRILDI — Excel index zorunlu kılmıyor;
        # gerekirse Excel'e grade_level kolonu eklenmeli (ileri iyileştirme).
        filters: dict = {"content_type": ct}
        if ct != "question" and request.query.taxonomic_level:
            filters["taxonomic_level"] = request.query.taxonomic_level
        if request.query.subject:
            filters["subject"] = request.query.subject

        top_k = request.top_k or self.settings.top_k

        # ── Embedding ──────────────────────────────────────────────
        # encode CPU-bound; başka coroutine'leri bloklamamak için thread'e sar
        try:
            vector = await asyncio.to_thread(self.embedder.embed_one, query_text)
        except Exception:
            logger.exception("[%s] embedding failed", request.trace_id)
            return ContentRetrievalResponse(
                correlation_id=request.correlation_id,
                trace_id=request.trace_id,
                chunks=[],
                total_found=0,
            )

        # ── Aşama 1: ilk eşikle ara ────────────────────────────────
        primary = await self.qdrant.search(
            query_vector=vector,
            filters=filters,
            top_k=top_k,
            score_threshold=self.settings.similarity_threshold,
        )

        # ── Hiç sonuç yoksa eşiği gevşet ───────────────────────────
        if not primary:
            relaxed = await self.qdrant.search(
                query_vector=vector,
                filters=filters,
                top_k=top_k,
                score_threshold=self.settings.similarity_threshold_relaxed,
            )
            primary = relaxed
            logger.info("[%s] strict threshold yielded 0; relaxed threshold returned %d",
                        request.trace_id, len(relaxed))

        # ── Aşama 2: rerank — sırala ve top_n al ───────────────────
        primary.sort(key=lambda c: c.score, reverse=True)
        top = primary[: self.settings.rerank_top_n]

        elapsed = (time.perf_counter() - start) * 1000.0
        logger.info(
            "[%s] retrieved %d/%d chunks (filters=%s, %.1fms)",
            request.trace_id, len(top), len(primary), filters, elapsed,
        )

        return ContentRetrievalResponse(
            correlation_id=request.correlation_id,
            trace_id=request.trace_id,
            chunks=top,
            total_found=len(primary),
        )
