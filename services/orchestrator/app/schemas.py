"""Pydantic schemas — Kafka mesaj contract'larının kod tarafı.

Şemalar CLAUDE.md'deki örneklerle uyumlu. trace_id ve correlation_id
alanları distributed tracing + request-response eşleşmesi için
şemanın üst kümesi olarak eklenmiş durumda.
"""
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# ─── Gateway → Orchestrator ──────────────────────────────────────────

class StudentInteractionPayload(BaseModel):
    question_id: str
    topic: str
    taxonomic_level: str
    student_answer: str
    is_correct: bool
    time_spent: int
    explicit_video_request: bool = False
    # Gateway, /api/answer body'sinden direkt aktarır. Orchestrator
    # error_explanation prompt'una gömerek LLM'in soru bağlamına vakıf
    # olmasını sağlar (yoksa RAG rastgele chunk üzerinden açıklama
    # üretiyor → soru-açıklama alakasızlığı).
    question_text: Optional[str] = None
    correct_answer: Optional[str] = None
    # qa_dialog için geçmiş mesajlar — Gateway Redis'ten çeker, payload'a
    # gömer. Liste her eleman: {"role": "user"|"assistant", "content": "..."}
    conversation_history: list[dict] = []


class StudentInteractionEvent(BaseModel):
    """student_interactions_stream'den gelen mesaj."""
    event_id: str
    trace_id: str
    student_id: str
    grade_level: int                           # Gateway JWT'den ekliyor (Step 3 değişikliği)
    event_type: str
    payload: StudentInteractionPayload
    timestamp: str


# ─── Bandit kararı (şimdilik sabit, gerçek Bandit servisi Step 4'te) ──

class BanditDecision(BaseModel):
    intervention_type: Literal["text", "step_by_step", "video"]
    difficulty_adjustment: str                 # taxonomic level (e.g. "B1")
    confidence_score: float


# ─── Orchestrator → RAG ──────────────────────────────────────────────

class ContentRetrievalQuery(BaseModel):
    subject: str
    taxonomic_level: str
    content_type: Literal["question", "theory", "explanation"]
    context: Optional[str] = None


class ContentRetrievalRequest(BaseModel):
    """content_retrieval_requests'e yazılan mesaj.

    Step 5b: grade_level alanı kaldırıldı. Excel index seviye-bağımsız
    olduğu için question chunks'larda grade_level metadata null kalıyor;
    filter göndermek tüm sonuçları dışlıyordu. Filtreleme tek başına
    `taxonomic_level` + `subject` üzerinden yapılır.
    """
    correlation_id: str
    trace_id: str
    student_id: str
    query: ContentRetrievalQuery
    top_k: int = 5
    timestamp: str


# ─── RAG → Orchestrator ──────────────────────────────────────────────

class RetrievedChunk(BaseModel):
    text: str
    score: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContentRetrievalResponse(BaseModel):
    """content_retrieval_responses'tan gelen mesaj."""
    correlation_id: str
    trace_id: str
    chunks: list[RetrievedChunk] = Field(default_factory=list)


# ─── Orchestrator → Bandit ──────────────────────────────────────────

class BanditDecisionRequest(BaseModel):
    """bandit_decision_requests'e yazılan mesaj."""
    correlation_id: str
    trace_id: str
    student_id: str
    context_vector: list[float]                # 12 floats (CLAUDE.md x_t)


class BanditDecisionPayload(BaseModel):
    intervention_type: Literal["text", "step_by_step", "video"]
    difficulty_adjustment: str
    confidence_score: float


class BanditDecisionResponse(BaseModel):
    """bandit_decision_responses'tan gelen mesaj."""
    correlation_id: str
    trace_id: str
    student_id: str
    decision: BanditDecisionPayload
    timestamp: str


# ─── Orchestrator → Bandit Learner ──────────────────────────────────

class RewardLogPayload(BaseModel):
    """reward_logs_stream'e yazılan mesaj.

    Bandit Learner DB-2'ye INSERT yaparken bu alanların hepsini kullanır.
    """
    correlation_id: str
    trace_id: str
    student_id: str

    context_vector: list[float]
    action_taken: int                          # 0=text, 1=step_by_step, 2=video

    c_t: float
    t_baseline: float
    t_actual: float
    s_t: float

    topic_id: str
    taxonomic_level: str
    is_correct: bool
    frustration_index: float = 0.0

    timestamp: str


# ─── Orchestrator → Gateway ──────────────────────────────────────────

class ContentDeliveryMessage(BaseModel):
    """content_delivery_stream'e yazılan mesaj.

    student_id top-level alanı: Gateway WebSocket routing için bunu kullanır.
    `context`: frontend routing'i için ek bilgi — örn. "chat" değeri
    geldiğinde useWebSocket hook mesajı chatHistory'ye append eder.
    """
    trace_id: str
    student_id: str
    content_type: Literal["text_explanation", "step_by_step", "video", "system_message"]
    body_html: str
    context: Optional[str] = None
    next_action: str = "wait_for_student"
    timestamp: str


# ─── Orchestrator → Manim Worker (Adım 6) ──────────────────────────

class ManimRenderTask(BaseModel):
    """manim_render_tasks topic'ine yazılan mesaj."""
    task_id: str
    correlation_id: str
    trace_id: str
    student_id: str
    manim_code: str
    render_quality: Literal["480p", "720p", "1080p"] = "720p"
    timeout_seconds: int = 45
    attempt_number: int = 1


# ─── Manim Worker → Orchestrator (qa_correction_loop) ──────────────

class QACorrectionRequest(BaseModel):
    task_id: str
    correlation_id: str
    trace_id: str
    student_id: str
    manim_code: str
    error_type: Literal[
        "AST_VIOLATION", "SYNTAX_ERROR", "RENDER_ERROR", "TIMEOUT", "UNKNOWN",
    ]
    error_message: str
    traceback_snippet: Optional[str] = None
    attempt_number: int
