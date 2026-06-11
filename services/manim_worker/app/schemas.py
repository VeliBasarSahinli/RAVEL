"""Pydantic şemaları — Kafka kontratının kod tarafı.

Adım 6:
  - manim_render_tasks      (consume)  → ManimRenderTask
  - qa_correction_loop      (produce)  → QACorrectionRequest
  - video_ready_events      (produce)  → VideoReadyEvent
  - dead_letter_queue_ravel (produce)  → DLQEvent

`student_id` top-level alanı her zaman var: Gateway WS routing için
ve trace gözlemlenebilirliği için zorunlu.
"""
from typing import Literal, Optional

from pydantic import BaseModel, Field


# ─── Orchestrator → Manim Worker ────────────────────────────────────

class ManimRenderTask(BaseModel):
    """manim_render_tasks topic'inden gelen mesaj."""
    task_id: str
    correlation_id: str
    trace_id: str
    student_id: str
    manim_code: str
    render_quality: Literal["480p", "720p", "1080p"] = "720p"
    timeout_seconds: int = 45
    attempt_number: int = 1


# ─── Manim Worker → Orchestrator (hata yolu) ────────────────────────

class QACorrectionRequest(BaseModel):
    """qa_correction_loop'a yazılan mesaj.

    Orchestrator bunu alınca LLM mock ile kod düzeltmesi tetikler ve
    yeni bir manim_render_tasks publish'ler (attempt_number+1).
    """
    task_id: str
    correlation_id: str
    trace_id: str
    student_id: str
    manim_code: str                         # son denenen kod
    error_type: Literal[
        "AST_VIOLATION",
        "SYNTAX_ERROR",
        "RENDER_ERROR",
        "TIMEOUT",
        "UNKNOWN",
    ]
    error_message: str
    traceback_snippet: Optional[str] = None
    attempt_number: int                     # bu attempt'in numarası (artırarak gönderilir)


# ─── Manim Worker → Gateway (başarı yolu) ───────────────────────────

class VideoReadyEvent(BaseModel):
    """video_ready_events'e yazılan mesaj. Gateway WS'ten student'a iter."""
    task_id: str
    correlation_id: str
    trace_id: str
    student_id: str
    content_type: Literal["video"] = "video"
    video_url: str
    duration_seconds: float
    file_size_bytes: int
    timestamp: str


# ─── Manim Worker → DLQ (3 deneme aşıldı) ───────────────────────────

class DLQEvent(BaseModel):
    """dead_letter_queue_ravel'e yazılan mesaj.

    Orchestrator bu mesajı tüketir ve fallback metin yanıt üretir.
    """
    task_id: str
    correlation_id: str
    trace_id: str
    student_id: str
    source_topic: str = "manim_render_tasks"
    reason: str
    attempts: int
    last_error_type: str
    last_error_message: str
    timestamp: str
