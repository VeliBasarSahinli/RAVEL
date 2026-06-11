"""Pydantic schemas for Bandit service.

CLAUDE.md'deki kanonik şemalardan extension'lar:
  RewardLogEntry — Step 4 spec'inde belirtilen 8 alana ek olarak,
  Learner'ın DB-2'ye CLAUDE.md interaction_logs'una uygun INSERT
  yapabilmesi için topic_id / taxonomic_level / is_correct /
  frustration_index alanları eklenmiştir.
"""
from typing import Literal

from pydantic import BaseModel, Field


# ─── Decision request/response (Orchestrator ↔ Bandit) ──────────────

class BanditDecisionRequest(BaseModel):
    correlation_id: str
    trace_id: str
    student_id: str
    context_vector: list[float]            # 12 floats expected


class BanditDecisionPayload(BaseModel):
    intervention_type: Literal["text", "step_by_step", "video"]
    difficulty_adjustment: str             # taxonomic level (e.g. "B1")
    confidence_score: float


class BanditDecisionResponse(BaseModel):
    correlation_id: str
    trace_id: str
    student_id: str
    decision: BanditDecisionPayload
    timestamp: str


# ─── Reward log (Orchestrator → Learner) ────────────────────────────

class RewardLogEntry(BaseModel):
    correlation_id: str
    trace_id: str
    student_id: str

    # Policy-update inputs
    context_vector: list[float]
    action_taken: int                      # 0=text, 1=step_by_step, 2=video

    # Reward components (CLAUDE.md formula)
    c_t: float                             # accuracy: -1, +0.5, +1
    t_baseline: float                      # ideal seconds
    t_actual: float                        # observed seconds
    s_t: float                             # self-rating in [-1, +1]

    # CLAUDE.md interaction_logs fields (extension for DB-2 INSERT)
    topic_id: str
    taxonomic_level: str
    is_correct: bool
    frustration_index: float = 0.0

    timestamp: str


# ─── DB-2 row (no JSON wire form; used internally) ──────────────────

class InteractionLogEntry(BaseModel):
    """Mirrors CLAUDE.md interaction_logs row exactly."""
    student_id: str
    topic_id: str
    taxonomic_level: str
    action_taken: Literal["text", "step_by_step", "video"]
    is_correct: bool
    time_spent_seconds: int = Field(ge=0)
    frustration_index: float = Field(ge=0.0, le=1.0)
    reward_signal: float
