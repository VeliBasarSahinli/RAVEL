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
    health_port: int = 8002

    # ─── Bağlantılar ───
    db2_dsn: str
    redis_url: str
    kafka_bootstrap_servers: str

    # ─── MinIO ───
    minio_endpoint: str
    minio_access_key: str
    minio_secret_key: str
    minio_bucket_weights: str = "bandit-weights"

    # ─── Kafka ───
    bandit_group_id: str = "bandit"  # base; suffix _actor / _learner
    kafka_topic_partitions: int = 10
    kafka_topic_replication: int = 1

    topic_bandit_decision_requests: str = "bandit_decision_requests"
    topic_bandit_decision_responses: str = "bandit_decision_responses"
    topic_reward_logs: str = "reward_logs_stream"

    # ─── Bandit algorithm ───
    bandit_num_actions: int = 3            # text / step_by_step / video
    bandit_context_dim: int = 12           # CLAUDE.md x_t vector size
    bandit_alpha: float = 1.0              # LinTS exploration coefficient
    bandit_mini_batch_size: int = 100
    bandit_mini_batch_timeout_seconds: int = 60
    actor_inference_timeout_ms: int = 50   # CLAUDE.md SLA

    # Test override — LinTS sampling'i bypass eder ve sabit aksiyon döner.
    # ADR-017 (Adım 6): video akışını deterministik test edebilmek için.
    # Boş string → override yok (varsayılan).
    # Geçerli değerler: text | step_by_step | video | manim_video (alias).
    bandit_force_decision: str = ""

    # ─── Reward formula (CLAUDE.md weights) ───
    reward_alpha: float = 0.6              # accuracy weight
    reward_beta: float = 0.2               # time-efficiency weight
    reward_gamma: float = 0.2              # self-rating weight
    # Cap on time_efficiency to avoid extreme values when T_actual is tiny.
    reward_time_efficiency_cap: float = 2.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
