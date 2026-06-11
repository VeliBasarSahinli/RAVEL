from functools import lru_cache
from typing import Optional

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
    admin_api_port: int = 8003

    # ─── Bağlantılar ───
    redis_url: str
    kafka_bootstrap_servers: str

    # ─── Qdrant ───
    qdrant_url: str = "http://qdrant:6333"
    qdrant_collection: str = "rag_knowledge_base"

    # ─── Embedding ───
    embedding_model: str = "paraphrase-multilingual-MiniLM-L12-v2"
    embedding_dim: int = 384
    embedding_cache_folder: Optional[str] = "/opt/models"  # build'de pre-downloaded
    embedding_batch_size: int = 64

    # ─── Retrieval ───
    similarity_threshold: float = 0.45
    similarity_threshold_relaxed: float = 0.30  # ilk eşik tutmazsa düşürülen seviye
    top_k: int = 8
    rerank_top_n: int = 3

    # ─── Kafka ───
    rag_group_id: str = "rag"
    kafka_topic_partitions: int = 10
    kafka_topic_replication: int = 1

    topic_content_retrieval_requests: str = "content_retrieval_requests"
    topic_content_retrieval_responses: str = "content_retrieval_responses"

    # ─── MinIO ───
    minio_endpoint: str
    minio_access_key: str
    minio_secret_key: str
    minio_bucket_content: str = "rag-content"
    # Excel index ve diğer process-memory state'ler için meta bucket;
    # restart sonrası restore için. Pickle pragmatik; admin-only veri.
    minio_bucket_meta: str = "ravel-config"
    excel_index_object_key: str = "excel_index/latest.pkl"

    # ─── JWT (admin auth — same secret as Gateway) ───
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"

    # ─── Adım 7e — LLM admin (DB-1 + AES key) ───
    # DB1_DSN boşsa /admin/llm/* endpoint'leri 503 döner.
    # ENCRYPTION_KEY boşsa api_key set edilemez (anthropic/openai/openrouter/gemini reddedilir).
    db1_dsn: str = ""
    encryption_key: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
