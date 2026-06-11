from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ─── Service ───
    log_level: str = "INFO"
    health_port: int = 8001

    # ─── Bağlantılar ───
    db1_dsn: str                                    # postgresql://ravel_app:pw@pgbouncer:6432/ravel_db1
    redis_url: str
    kafka_bootstrap_servers: str

    # ─── Kafka ───
    orchestrator_group_id: str = "orchestrator"
    kafka_topic_partitions: int = 10
    kafka_topic_replication: int = 1

    # Topic adları (CLAUDE.md)
    topic_student_interactions: str = "student_interactions_stream"
    topic_content_retrieval_requests: str = "content_retrieval_requests"
    topic_content_retrieval_responses: str = "content_retrieval_responses"
    topic_content_delivery: str = "content_delivery_stream"
    topic_bandit_decision_requests: str = "bandit_decision_requests"
    topic_bandit_decision_responses: str = "bandit_decision_responses"
    topic_reward_logs: str = "reward_logs_stream"
    # Adım 6 — Manim Worker iletişimi
    topic_manim_render_tasks: str = "manim_render_tasks"
    topic_qa_correction_loop: str = "qa_correction_loop"
    topic_video_ready_events: str = "video_ready_events"
    topic_dlq: str = "dead_letter_queue_ravel"

    # ─── İş akışı parametreleri ───
    rag_request_timeout_seconds: int = 3
    rag_circuit_fail_max: int = 5
    rag_circuit_reset_timeout: int = 60
    rag_fallback_text: str = "Şu an içerik yüklenemiyor, lütfen bekleyin."

    # ─── LLM ───
    llm_mock_mode: bool = True

    # ─── RAG sorgusu için varsayılanlar ───
    rag_top_k: int = 5

    # ─── Bandit (Step 4) ───
    bandit_request_timeout_ms: int = 200          # CLAUDE.md SLA <50ms + Kafka buffer
    bandit_t_baseline_seconds: float = 60.0       # ideal solution time

    # ─── Pending interaction state (gecikmeli ödül) ───
    pending_interaction_ttl_seconds: int = 1800   # 30 dk, CLAUDE.md

    # ─── Manim Worker (Adım 6) ───
    manim_max_retries: int = 3                     # CLAUDE.md SLA
    manim_render_timeout_seconds: int = 45         # CLAUDE.md SLA
    manim_video_quality: str = "720p"
    # Bandit "video" kararından sonra video_ready_events için bekleme süresi.
    # Render 45 sn olabilir + sandbox + upload buffer + Kafka jitter.
    video_ready_timeout_seconds: int = 90

    # ─── LLM Gateway (Adım 7) ───
    encryption_key: str = ""                       # 64 hex chars (AES-256). Boş ise gateway sadece mock'ta çalışır.
    llm_request_timeout_seconds: float = 60.0      # tek bir provider çağrısı için
    # DB-2 read-only — Adım 7d için consecutive_errors / success_rate
    db2_dsn: str = ""                              # opsiyonel: boşsa hesaplama atlanır


@lru_cache
def get_settings() -> Settings:
    return Settings()
