"""RAG service entry point.

İki paralel task (ADR-013):
  1) FastAPI/uvicorn admin server (port 8003)
  2) Kafka consumer (content_retrieval_requests) → Retriever → producer

Lifespan:
  startup → embedder.load, qdrant.start (collection ensure),
            ensure_topics, kafka producer/consumer start,
            uvicorn server start
  loop    → SIGTERM/SIGINT bekle
  cleanup → consumer.stop, producer.stop, qdrant.stop, server.shutdown
"""
import asyncio
import logging
import signal
from typing import Any, Optional

import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError
import uvicorn

from redis.asyncio import Redis

from .admin_api import build_admin_app
from .config import Settings, get_settings
from .crypto import ApiKeyCipher, CryptoError
from .db1_io import DB1Pool
from .embedder import Embedder
from .ingestion_pipeline import IngestionPipeline
from .kafka_io import KafkaConsumer, KafkaProducer, ensure_topics
from .llm_configs_repo import LLMConfigsRepo
from .qdrant_io import QdrantIO
from .retriever import Retriever
from .schemas import ContentRetrievalRequest

logger = logging.getLogger("rag")


def _make_minio_client(settings: Settings):
    return boto3.client(
        "s3",
        endpoint_url=settings.minio_endpoint,
        aws_access_key_id=settings.minio_access_key,
        aws_secret_access_key=settings.minio_secret_key,
        config=BotoConfig(signature_version="s3v4", retries={"max_attempts": 3}),
        region_name="us-east-1",
    )


def _ensure_minio_bucket(client, bucket: str) -> None:
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code")
        if code in ("404", "NoSuchBucket", "NotFound"):
            client.create_bucket(Bucket=bucket)
            logger.info("MinIO: created bucket '%s'", bucket)
        else:
            raise


async def main() -> None:
    settings: Settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger.info("rag starting")

    # ── Embedder (model already in image; load is fast) ───────────
    embedder = Embedder(
        model_name=settings.embedding_model,
        cache_folder=settings.embedding_cache_folder,
        batch_size=settings.embedding_batch_size,
    )
    embedder.load()

    # ── Qdrant ─────────────────────────────────────────────────────
    qdrant = QdrantIO(
        url=settings.qdrant_url,
        collection=settings.qdrant_collection,
        vector_dim=settings.embedding_dim,
    )
    await qdrant.start()

    # ── Kafka topics ────────────────────────────────────────────────
    await ensure_topics(
        settings.kafka_bootstrap_servers,
        topics=[
            settings.topic_content_retrieval_requests,
            settings.topic_content_retrieval_responses,
        ],
        num_partitions=settings.kafka_topic_partitions,
        replication_factor=settings.kafka_topic_replication,
    )

    # ── MinIO ─────────────────────────────────────────────────────
    minio_client = _make_minio_client(settings)
    try:
        _ensure_minio_bucket(minio_client, settings.minio_bucket_content)
        _ensure_minio_bucket(minio_client, settings.minio_bucket_meta)
    except Exception:
        logger.exception("MinIO bucket ensure failed (continuing without)")
        minio_client = None

    # ── Producer + Consumer ────────────────────────────────────────
    producer = KafkaProducer(settings.kafka_bootstrap_servers)
    await producer.start()

    pipeline = IngestionPipeline(
        embedder=embedder,
        qdrant=qdrant,
        minio_client=minio_client,
        minio_bucket=settings.minio_bucket_content if minio_client else None,
        minio_meta_bucket=settings.minio_bucket_meta if minio_client else None,
        excel_index_object_key=settings.excel_index_object_key,
    )

    # Restart sonrası Excel index'i restore et — admin manuel reupload
    # gerekmesin. Boto3 senkron olduğu için executor'da çalışır.
    try:
        restored = await pipeline.restore_excel_index()
        if restored:
            logger.info("Excel index restored on startup (rows=%d)", pipeline.excel_index_size)
        else:
            logger.info("No persisted Excel index found — admin upload needed")
    except Exception:
        logger.exception("Excel index restore failed (continuing without)")

    retriever = Retriever(settings, embedder, qdrant)

    async def consumer_handler(topic: str, value: dict[str, Any]) -> None:
        try:
            request = ContentRetrievalRequest(**value)
        except Exception:
            logger.exception("invalid ContentRetrievalRequest payload: %s", value)
            return
        response = await retriever.retrieve(request)
        await producer.send(
            settings.topic_content_retrieval_responses,
            response.model_dump(),
            key=request.correlation_id,
        )

    consumer = KafkaConsumer(
        settings.kafka_bootstrap_servers,
        topics=[settings.topic_content_retrieval_requests],
        group_id=settings.rag_group_id,
    )
    await consumer.start(consumer_handler)

    # ── Adım 7e: DB-1 + cipher + Redis (admin LLM endpoint'leri için) ─
    db1_pool: DB1Pool | None = None
    llm_repo: LLMConfigsRepo | None = None
    if settings.db1_dsn:
        try:
            db1_pool = DB1Pool(settings.db1_dsn)
            await db1_pool.start()
            llm_repo = LLMConfigsRepo(db1_pool.pool)
            logger.info("DB-1 connected; LLM admin endpoints active")
        except Exception:
            logger.exception("DB-1 connect failed; LLM admin endpoints will return 503")
            db1_pool = None
            llm_repo = None
    else:
        logger.info("DB1_DSN empty; LLM admin endpoints disabled")

    cipher: ApiKeyCipher | None = None
    if settings.encryption_key:
        try:
            cipher = ApiKeyCipher(settings.encryption_key)
        except CryptoError as e:
            logger.error("ENCRYPTION_KEY invalid (%s); admin can list/delete but not set api_key", e)

    redis_client: Redis | None = None
    try:
        redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
        await redis_client.ping()
    except Exception:
        logger.exception("Redis client failed; cache invalidation disabled")
        redis_client = None

    # ── FastAPI admin (uvicorn programmatic) ──────────────────────
    admin_app = build_admin_app(
        settings, pipeline, qdrant,
        llm_repo=llm_repo, cipher=cipher, redis_client=redis_client,
    )
    uvicorn_config = uvicorn.Config(
        admin_app,
        host="0.0.0.0",
        port=settings.admin_api_port,
        log_level=settings.log_level.lower(),
        access_log=False,
    )
    uvicorn_server = uvicorn.Server(uvicorn_config)
    server_task = asyncio.create_task(uvicorn_server.serve())

    # ── Signal handling ───────────────────────────────────────────
    stop_event = asyncio.Event()

    def _signal_handler(signum: int) -> None:
        logger.info("received signal %d", signum)
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _signal_handler, sig)
        except NotImplementedError:
            pass

    logger.info("rag ready (group_id=%s, admin_port=%d)",
                settings.rag_group_id, settings.admin_api_port)

    await stop_event.wait()

    logger.info("rag shutting down")
    uvicorn_server.should_exit = True
    await consumer.stop()
    await producer.stop()
    await qdrant.stop()
    if db1_pool is not None:
        await db1_pool.stop()
    if redis_client is not None:
        try:
            await redis_client.aclose()
        except Exception:
            pass
    try:
        await asyncio.wait_for(server_task, timeout=5.0)
    except asyncio.TimeoutError:
        server_task.cancel()
    logger.info("rag stopped")


if __name__ == "__main__":
    asyncio.run(main())
