"""Bandit entry point — Actor + Learner aynı container'da iki ayrı task.

Lifespan:
  startup → ensure_topics, MinIO bucket, DB pool, Redis,
            Kafka producer, Actor.start(), Learner.start(),
            iki KafkaConsumer (actor / learner consumer group'ları),
            health TCP listener
  loop    → SIGTERM/SIGINT bekle
  cleanup → consumer'ları durdur, Learner.stop, Actor.stop,
            producer, DB, Redis, MinIO (ters sıra)
"""
import asyncio
import logging
import signal
from typing import Any

from .actor import ActorService
from .config import Settings, get_settings
from .db_io import DB2Client
from .kafka_io import KafkaConsumer, KafkaProducer, ensure_topics
from .learner import LearnerService
from .minio_io import MinIOClient
from .redis_io import RedisIO

logger = logging.getLogger("bandit")


async def _health_server(stop_event: asyncio.Event, port: int) -> None:
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass

    server = await asyncio.start_server(handle, "0.0.0.0", port)
    logger.info("health TCP server listening on :%d", port)
    try:
        await stop_event.wait()
    finally:
        server.close()
        await server.wait_closed()


async def main() -> None:
    settings: Settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger.info("bandit starting (Actor + Learner)")

    # ── Clients ─────────────────────────────────────────────────────
    db = DB2Client(settings.db2_dsn)
    redis_io = RedisIO(settings.redis_url)
    producer = KafkaProducer(settings.kafka_bootstrap_servers)
    minio = MinIOClient(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        bucket=settings.minio_bucket_weights,
    )

    # ── Ensure Kafka topics (the new one is reward_logs_stream) ─────
    await ensure_topics(
        settings.kafka_bootstrap_servers,
        topics=[
            settings.topic_bandit_decision_requests,
            settings.topic_bandit_decision_responses,
            settings.topic_reward_logs,
        ],
        num_partitions=settings.kafka_topic_partitions,
        replication_factor=settings.kafka_topic_replication,
    )

    # ── Bring infra up (order matters) ──────────────────────────────
    await db.start()
    await redis_io.start()
    await minio.start()
    await minio.ensure_bucket()
    await producer.start()

    # ── Services ────────────────────────────────────────────────────
    actor = ActorService(settings, producer, minio, redis_io)
    learner = LearnerService(settings, db, minio, redis_io)
    await actor.start()
    await learner.start()

    # ── Two consumers — Actor and Learner are isolated by group_id ──
    async def actor_handler(topic: str, value: dict[str, Any]) -> None:
        await actor.handle_request(value)

    async def learner_handler(topic: str, value: dict[str, Any]) -> None:
        await learner.handle_reward(value)

    actor_consumer = KafkaConsumer(
        settings.kafka_bootstrap_servers,
        topics=[settings.topic_bandit_decision_requests],
        group_id=f"{settings.bandit_group_id}-actor",
    )
    learner_consumer = KafkaConsumer(
        settings.kafka_bootstrap_servers,
        topics=[settings.topic_reward_logs],
        group_id=f"{settings.bandit_group_id}-learner",
    )
    await actor_consumer.start(actor_handler)
    await learner_consumer.start(learner_handler)

    # ── Signal handling ─────────────────────────────────────────────
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

    health_task = asyncio.create_task(_health_server(stop_event, settings.health_port))

    logger.info(
        "bandit ready (actor_group=%s, learner_group=%s, n_actions=%d, dim=%d)",
        f"{settings.bandit_group_id}-actor",
        f"{settings.bandit_group_id}-learner",
        settings.bandit_num_actions,
        settings.bandit_context_dim,
    )

    await stop_event.wait()

    # ── Graceful shutdown (reverse order) ──────────────────────────
    logger.info("bandit shutting down")
    await actor_consumer.stop()
    await learner_consumer.stop()
    await learner.stop()
    await actor.stop()
    await producer.stop()
    await minio.stop()
    await redis_io.stop()
    await db.stop()
    health_task.cancel()
    try:
        await health_task
    except asyncio.CancelledError:
        pass
    logger.info("bandit stopped")


if __name__ == "__main__":
    asyncio.run(main())
