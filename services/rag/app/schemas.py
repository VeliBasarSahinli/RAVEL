"""Pydantic schemas for RAG service."""
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# ─── Kafka request-response ───────────────────────────────────────────

class ContentRetrievalQuery(BaseModel):
    """Inner query block (mirror of Orchestrator's schema)."""
    subject: Optional[str] = None
    taxonomic_level: Optional[str] = None
    content_type: Literal["question", "theory", "explanation"] = "explanation"
    context: Optional[str] = None


class ContentRetrievalRequest(BaseModel):
    """content_retrieval_requests'ten gelen mesaj."""
    correlation_id: str
    trace_id: str
    student_id: Optional[str] = None
    query: ContentRetrievalQuery
    grade_level: Optional[int] = None
    top_k: Optional[int] = None
    timestamp: Optional[str] = None


class RetrievedChunk(BaseModel):
    chunk_id: str
    text: str
    score: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContentRetrievalResponse(BaseModel):
    """content_retrieval_responses'a yazılan mesaj."""
    correlation_id: str
    trace_id: str
    chunks: list[RetrievedChunk] = Field(default_factory=list)
    total_found: int = 0


# ─── Internal pipeline types ──────────────────────────────────────────

class QuestionMeta(BaseModel):
    """Excel index'inden çıkarılan tek soru metadatası."""
    file_name: str
    test_no: Optional[int] = None
    question_number: int
    taxonomic_level: str
    answer_key: Optional[str] = None


class ParsedChunk(BaseModel):
    """Parser'dan çıkıp embedder/qdrant'a gidecek bir chunk."""
    chunk_id: str
    text_content: str
    text_for_embedding: str             # normalize edilmiş hali (LaTeX → Türkçe)
    metadata: dict[str, Any] = Field(default_factory=dict)
    has_image: bool = False


# ─── Admin API ────────────────────────────────────────────────────────

class UploadResponse(BaseModel):
    file_name: str
    rows_or_chunks: int
    message: str


class IngestionResult(BaseModel):
    file_name: str
    file_type: str
    parsed_chunks: int
    embedded_chunks: int
    written_chunks: int
    skipped_chunks: int                 # has_image=True veya çok kısa metin
    failed_chunks: int
    processing_time_seconds: float


class CollectionStats(BaseModel):
    total_chunks: int
    by_content_type: dict[str, int]
    by_grade_level: dict[str, int]
    # Adım 8 Faz 4 — admin paneli "İstatistikler" sekmesi konu-bazlı bar chart
    # için file_name dağılımı bekler. Mevcut Qdrant'ta veri yoksa boş dict.
    by_file_name: dict[str, int] = {}
    collection_name: str
    vector_dim: int
