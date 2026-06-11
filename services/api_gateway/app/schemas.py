from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ─── Auth — legacy + Adım 8 ─────────────────────────────────────────

class LoginRequest(BaseModel):
    """Backwards-compatible login.

    İki mod:
      1) `username` + `password`  → Adım 8 auth path (DB lookup, bcrypt verify)
      2) `grade_level` (yalnız)   → legacy anonim akış (Adım 2a — student_id mint
         et, JWT döndür). Test scriptleri bunu kullanmaya devam eder.

    `role` alanı yalnız mod (2)'de admin token üretmek için.
    """
    username: Optional[str] = None
    password: Optional[str] = None
    student_id: Optional[UUID] = None
    grade_level: Optional[int] = Field(default=None, ge=5, le=8)
    role: Optional[str] = None


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    student_id: UUID
    role: str = "student"
    display_name: Optional[str] = None


class RegisterRequest(BaseModel):
    """POST /auth/register — admin token gerekli.

    grade_level opsiyonel: kayıtta verilmezse Gateway default 6 yazar, ama
    bu yalnızca DB cold-start placeholder'ı; öğrenci runtime'da sidebar'dan
    sınıf seçer ve her interaction'a o sınıfı override olarak gönderir.
    """
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=6, max_length=128)
    grade_level: Optional[int] = Field(default=None, ge=5, le=8)
    display_name: Optional[str] = Field(default=None, max_length=128)
    role: str = Field(default="student", pattern=r"^(student|admin)$")


class RegisterResponse(BaseModel):
    student_id: UUID
    username: str
    role: str


class ProfileResponse(BaseModel):
    """GET /auth/me + temel alan; /api/profile gamification ekler."""
    student_id: UUID
    username: Optional[str]
    role: str
    grade_level: int
    display_name: Optional[str]


class GamificationProfile(ProfileResponse):
    """GET /api/profile — XP / streak / today_correct."""
    xp: int
    streak: int
    today_correct: int
    correct_total: int
    total_attempts: int
    success_rate: float


# ─── Question / Chat — Adım 8j ──────────────────────────────────────

class QuestionOption(BaseModel):
    key: str             # "A", "B", "C", "D", (opsiyonel "E")
    text: str


class QuestionResponse(BaseModel):
    """GET /api/question — RAG'dan parse edilmiş soru."""
    question_id: str
    topic: str
    taxonomic_level: str
    question_text: str
    options: list[QuestionOption]
    answer_key: Optional[str] = None         # A/B/C/D/E
    metadata: dict[str, Any] = Field(default_factory=dict)
    exhausted: bool = False                  # tüm sorular bitince true (zorunlu false)


class QuestionExhaustedResponse(BaseModel):
    """GET /api/question — bu öğrenci o konudaki tüm soruları çözmüş.

    HTTP 200 ile döner (404 değil — frontend tek bir endpoint contract'ı
    parse etsin, exhausted=true bayrağıyla "tüm sorular tamamlandı"
    UX'ine geçsin)."""
    exhausted: bool = True
    topic: str
    taxonomic_level: str
    total_asked: int
    message: str = "Tüm sorular tamamlandı"


class ChatRequest(BaseModel):
    """POST /api/chat — qa_dialog modunda öğretmenle konuşma."""
    message: str = Field(min_length=1, max_length=2000)
    topic: Optional[str] = None              # opsiyonel context
    taxonomic_level: Optional[str] = None
    # Frontend sidebar'daki aktif sınıfı her istekte gönderir; verilmezse JWT default'u.
    grade_level: Optional[int] = Field(default=None, ge=5, le=8)


class ChatAck(BaseModel):
    """Sync ack; gerçek yanıt WebSocket üzerinden gelir (content_delivery_stream)."""
    status: str = "accepted"
    trace_id: str
    message: str


# ─── Mevcut: interaction submit ─────────────────────────────────────

class AnswerRequest(BaseModel):
    """Body of POST /api/answer.

    Mirrors the inner payload of CLAUDE.md's student_interactions_stream
    schema (the gateway wraps it with event_id / trace_id / timestamp).

    Adım 8: opsiyonel `grade_level` per-request override — sidebar'daki aktif
    sınıf JWT'deki kayıt sınıfından bağımsız (öğrenci 8'inci sınıf kayıtlı
    ama 6. sınıf konularını çözüyor olabilir).

    Düzeltme 1 (production-grade): question_text + correct_answer da
    yollanır. Aksi halde Orchestrator hangi soruda hata yapıldığını
    bilmediğinden RAG'dan rastgele bir chunk çekip ona göre açıklama
    üretiyor — soru-açıklama alakasızlığı oluşuyordu.
    """
    question_id: str
    topic: str
    taxonomic_level: str
    student_answer: str
    is_correct: bool
    time_spent: int = Field(ge=0)
    explicit_video_request: bool = False
    grade_level: Optional[int] = Field(default=None, ge=5, le=8)
    # LLM bağlamı için soru metni + doğru cevap. Frontend sorudan elde eder.
    question_text: Optional[str] = Field(default=None, max_length=4000)
    correct_answer: Optional[str] = Field(default=None, max_length=8)
