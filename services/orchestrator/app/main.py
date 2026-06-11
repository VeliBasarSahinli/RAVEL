"""Orchestrator entry point — Step 4 versiyonu.

Lifespan:
  startup → ensure_topics, db.start, redis.start, producer.start,
            consumer.start (3 topic), health TCP listener
  loop    → SIGTERM/SIGINT bekle
  cleanup → consumer.stop, producer.stop, redis.stop, db.stop
"""
import asyncio
import logging
import signal
from typing import Any

from .circuit_breaker import RAGCircuitBreaker
from .config import Settings, get_settings
from .crypto import ApiKeyCipher, CryptoError
from .db_io import DB1Client
from .db2_io import DB2ReadClient
from .kafka_io import KafkaConsumer, KafkaProducer, ensure_topics
from .llm_client import LLMClient
from .llm_configs_repo import LLMConfigsRepo
from .llm_gateway import LLMGateway
from .prompt_engine import PromptEngine, PromptEngineError
from .redis_io import RedisIO
from datetime import datetime, timezone

from .schemas import ContentDeliveryMessage, StudentInteractionEvent
from .workflow import OrchestrationWorkflow, PendingResponseRegistry


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

logger = logging.getLogger("orchestrator")


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
    logger.info("orchestrator starting")

    db = DB1Client(settings.db1_dsn)
    redis_io = RedisIO(settings.redis_url)
    producer = KafkaProducer(settings.kafka_bootstrap_servers)
    llm = LLMClient(mock_mode=settings.llm_mock_mode)

    # Adım 7 — LLM Gateway (DB-1'deki llm_configs üzerinden provider routing).
    # ENCRYPTION_KEY boş ise cipher None: mock dışında her çağrı LLMError verir.
    cipher: ApiKeyCipher | None = None
    if settings.encryption_key:
        try:
            cipher = ApiKeyCipher(settings.encryption_key)
            logger.info("AES-256-GCM cipher loaded for llm_configs.api_key")
        except CryptoError as e:
            logger.error("ENCRYPTION_KEY invalid (%s) — gateway will refuse non-mock calls", e)
    else:
        logger.warning("ENCRYPTION_KEY empty — LLM gateway in mock-only mode")

    breaker = RAGCircuitBreaker(
        fail_max=settings.rag_circuit_fail_max,
        reset_timeout=settings.rag_circuit_reset_timeout,
        fallback_text=settings.rag_fallback_text,
    )
    rag_registry = PendingResponseRegistry("RAG")
    bandit_registry = PendingResponseRegistry("Bandit")

    # Adım 7c: prompt template engine
    try:
        prompt_engine: PromptEngine | None = PromptEngine()
        logger.info("Prompt engine loaded (%d modes)", len(prompt_engine.modes()))
    except PromptEngineError as e:
        logger.error("Prompt engine init failed (%s) — falling back to legacy LLMClient", e)
        prompt_engine = None

    # Adım 7d: DB-2 read client (opsiyonel — DSN boşsa skip)
    db2: DB2ReadClient | None = None
    if settings.db2_dsn:
        db2 = DB2ReadClient(settings.db2_dsn)

    workflow = OrchestrationWorkflow(
        settings, db, redis_io, producer, llm, breaker, rag_registry, bandit_registry,
        prompt_engine=prompt_engine, db2=db2,
    )

    # Topic'ler — orchestrator'ın doğrudan dokunduğu hepsi
    await ensure_topics(
        settings.kafka_bootstrap_servers,
        topics=[
            settings.topic_student_interactions,
            settings.topic_content_retrieval_requests,
            settings.topic_content_retrieval_responses,
            settings.topic_content_delivery,
            settings.topic_bandit_decision_requests,
            settings.topic_bandit_decision_responses,
            settings.topic_reward_logs,
            # Adım 6 — Manim Worker bağlantısı
            settings.topic_manim_render_tasks,
            settings.topic_qa_correction_loop,
            settings.topic_dlq,
        ],
        num_partitions=settings.kafka_topic_partitions,
        replication_factor=settings.kafka_topic_replication,
    )

    await db.start()
    if db2 is not None:
        try:
            await db2.start()
            logger.info("DB-2 read client connected")
        except Exception:
            logger.exception("DB-2 client failed to start; continuing without stats")
            db2 = None
            workflow.db2 = None
    await redis_io.start()
    await producer.start()

    # LLM Gateway: db.pool zorunlu (repo için), redis_io start sonrası cache aktif.
    llm_repo = LLMConfigsRepo(db.pool)
    llm_gateway = LLMGateway(
        repo=llm_repo,
        cipher=cipher,
        redis_io=redis_io,
        mock_mode=settings.llm_mock_mode,
        request_timeout_seconds=settings.llm_request_timeout_seconds,
    )
    await llm_gateway.start()
    workflow.llm_gateway = llm_gateway   # Adım 7d'de aktive edilecek
    logger.info("LLM Gateway started (mock_mode=%s)", settings.llm_mock_mode)

    # ── İKİ AYRI CONSUMER (deadlock prevention, ADR-013) ──────────
    # Tek consumer ile interactions + responses dinlemek workflow'un
    # await-bloklamasını response consumer'ın bloke etmesine yol açıyor.
    # İki ayrı group_id altında iki Kafka consumer task'ı kullanıyoruz.

    async def interactions_handler(topic: str, value: dict[str, Any]) -> None:
        # Schema validation hatası dışarıya bırakılıyor — kafka_io.py
        # outer loop "handler failed" log'u atar (robustness Test 1: bozuk
        # JSON izolasyonu). Bu sayede auto-commit ile bozuk mesaj atlansa
        # bile loop crash etmez.
        event = StudentInteractionEvent(**value)
        # Workflow runtime exception'ları öğrenciye fallback delivery olarak
        # dönsün — aksi halde kullanıcı sonsuza kadar "Açıklama bekleniyor…"
        # görür (Bulgu 10).
        try:
            await workflow.process_interaction(event)
        except Exception:
            logger.exception(
                "[%s] process_interaction unhandled — sending fallback delivery",
                event.trace_id,
            )
            try:
                fallback = ContentDeliveryMessage(
                    trace_id=event.trace_id,
                    student_id=event.student_id,
                    content_type="text_explanation",
                    body_html="Şu an bir sorun oluştu. Lütfen tekrar deneyin.",
                    next_action="wait_for_student",
                    timestamp=_now_iso(),
                )
                await producer.send(
                    settings.topic_content_delivery,
                    fallback.model_dump(),
                    key=event.student_id,
                )
            except Exception:
                logger.exception("[%s] fallback delivery also failed", event.trace_id)

    async def responses_handler(topic: str, value: dict[str, Any]) -> None:
        if topic == settings.topic_content_retrieval_responses:
            corr = value.get("correlation_id")
            if not corr:
                logger.warning("RAG response without correlation_id: %s", value)
                return
            await rag_registry.deliver(corr, value)
        elif topic == settings.topic_bandit_decision_responses:
            corr = value.get("correlation_id")
            if not corr:
                logger.warning("Bandit response without correlation_id: %s", value)
                return
            await bandit_registry.deliver(corr, value)
        # Adım 6 — Manim akışı:
        elif topic == settings.topic_qa_correction_loop:
            await workflow.handle_qa_correction(value)
        elif topic == settings.topic_dlq:
            await workflow.handle_dlq(value)
        else:
            logger.warning("unexpected topic on responses_consumer: %s", topic)

    interactions_consumer = KafkaConsumer(
        settings.kafka_bootstrap_servers,
        topics=[settings.topic_student_interactions],
        group_id=settings.orchestrator_group_id,
    )
    # ADR-013: response/feedback topic'leri ayrı consumer (deadlock prevention).
    # Adım 6'da qa_correction_loop ve dead_letter_queue da burada — uzun süren
    # bir handler yok (sadece producer.send), interactions_consumer'ı bloke etmez.
    responses_consumer = KafkaConsumer(
        settings.kafka_bootstrap_servers,
        topics=[
            settings.topic_content_retrieval_responses,
            settings.topic_bandit_decision_responses,
            settings.topic_qa_correction_loop,
            settings.topic_dlq,
        ],
        group_id=f"{settings.orchestrator_group_id}-responses",
    )
    await interactions_consumer.start(interactions_handler)
    await responses_consumer.start(responses_handler)

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

    logger.info("orchestrator ready (group_id=%s)", settings.orchestrator_group_id)
    await stop_event.wait()

    logger.info("orchestrator shutting down")
    await interactions_consumer.stop()
    await responses_consumer.stop()
    await llm_gateway.stop()
    await producer.stop()
    await redis_io.stop()
    if db2 is not None:
        await db2.stop()
    await db.stop()
    health_task.cancel()
    try:
        await health_task
    except asyncio.CancelledError:
        pass
    logger.info("orchestrator stopped")


if __name__ == "__main__":
    asyncio.run(main())
