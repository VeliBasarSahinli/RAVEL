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
    health_port: int = 8004

    # ─── Bağlantılar ───
    kafka_bootstrap_servers: str

    # ─── MinIO ───
    minio_endpoint: str
    minio_access_key: str
    minio_secret_key: str
    minio_bucket_videos: str = "ravel-videos"

    # ─── Kafka ───
    manim_worker_group_id: str = "manim_worker"
    manim_worker_qa_group_id: str = "manim_worker_qa"
    kafka_topic_partitions: int = 10
    kafka_topic_replication: int = 1

    # Topic adları (CLAUDE.md)
    topic_manim_render_tasks: str = "manim_render_tasks"
    topic_qa_correction_loop: str = "qa_correction_loop"
    topic_video_ready_events: str = "video_ready_events"
    topic_dlq: str = "dead_letter_queue_ravel"

    # ─── Render parametreleri ───
    manim_max_retries: int = 3                       # CLAUDE.md SLA
    manim_render_timeout_seconds: int = 45           # CLAUDE.md SLA
    manim_video_quality: str = "720p"                # 480p|720p|1080p
    manim_temp_dir: str = "/tmp/manim_renders"

    # ─── Sandbox parametreleri ───
    # AST whitelist: bunların dışındaki TÜM import'lar reddedilir.
    # ADR-017 (whitelist tercihi). String virgülle ayrılmış,
    # config tarafında set'e parse ediliyor.
    sandbox_allowed_imports: str = "manim,numpy,math,random"
    sandbox_syntax_check_timeout_seconds: int = 5    # py_compile + ast.parse subprocess

    # ─── Presigned URL ───
    video_url_expiration_seconds: int = 7 * 24 * 3600   # 7 gün
    # Tarayıcı içinden erişilebilir URL prefix'i. Boto3 presigned URL'sini
    # http://minio:9000/... → {public_prefix}/... olarak rewrite eder.
    # Frontend nginx'i /minio-videos/ path'ini Host: minio:9000 header'ıyla
    # MinIO'ya proxyler → SigV4 imzası geçerli kalır (Host header imzaya
    # dahil ve backward proxy nginx tarafında set ediliyor).
    minio_public_url_prefix: str = "/minio-videos"


@lru_cache
def get_settings() -> Settings:
    return Settings()
