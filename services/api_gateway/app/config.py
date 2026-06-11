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
    api_gateway_port: int = 8000
    log_level: str = "INFO"

    # ─── JWT ───
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_expiration_seconds: int = 7200  # 2 hours, per spec

    # ─── Redis ───
    redis_url: str  # e.g. redis://:password@redis:6379/0

    # ─── Kafka ───
    kafka_bootstrap_servers: str  # e.g. kafka:9092

    # ─── Topic names (CLAUDE.md) ───
    topic_student_interactions: str = "student_interactions_stream"
    topic_session_lifecycle: str = "session_lifecycle_events"
    topic_content_delivery: str = "content_delivery_stream"
    topic_video_ready: str = "video_ready_events"

    # ─── Behavioral knobs ───
    pending_message_ttl_seconds: int = 300   # 5 minutes for unrouted downstream messages
    session_ttl_seconds: int = 7200          # session:{student_id} TTL in Redis
    kafka_topic_partitions: int = 10         # CLAUDE.md SLA
    kafka_topic_replication: int = 1         # dev single broker

    # ─── Adım 8 — DB + CORS + RAG proxy ───
    db1_dsn: str = ""                                           # students table (auth)
    db2_dsn: str = ""                                           # interaction_logs (gamification)
    frontend_origin: str = "http://localhost:5173"              # comma-separated allowlist
    # /api/question için RAG content_retrieval_responses bekleme süresi
    question_request_timeout_seconds: float = 5.0
    topic_content_retrieval_requests: str = "content_retrieval_requests"
    topic_content_retrieval_responses: str = "content_retrieval_responses"
    # Aynı (öğrenci, konu) için tekrar dönmeyecek soru havuzu top_k +
    # asked-set TTL (aynı oturum boyunca tekrar etmesin; süresi dolunca
    # tüm sorulardan yeniden seçilebilir hale gelsin).
    question_top_k: int = 10
    asked_questions_ttl_seconds: int = 3600  # 1 saat = bir öğrenme oturumu
    # /api/stats proxy — RAG admin paneli /admin/stats endpoint'i admin token
    # gerektiriyor. Frontend'in TopicGrid'i öğrenci token'ıyla aynı veriyi
    # almak istiyor (hangi konularda chunk var). Gateway server-side bir
    # admin JWT mint eder (jwt_secret_key paylaşımlı) ve RAG'a iletir.
    rag_internal_url: str = "http://rag:8003"


@lru_cache
def get_settings() -> Settings:
    return Settings()
