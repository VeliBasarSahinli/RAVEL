"""Manim Worker entry point — saf async Python.

Lifespan:
  startup → ensure_topics, MinIO bucket, render dizini, Kafka producer,
            iki consumer (manim_render_tasks + qa_correction_loop'tan
            gelen düzeltilmiş kodlar), health TCP listener.
  loop    → SIGTERM/SIGINT bekle.
  cleanup → consumer.stop, producer.stop, MinIO close.

Akış (her ManimRenderTask için):
  1. SandboxValidator.validate(code)
     - AST_VIOLATION veya SYNTAX_ERROR → qa_correction_loop'a yaz; durdur.
  2. ManimRenderer.render(code, task_id)
     - RenderError → qa_correction_loop'a yaz; durdur.
  3. attempt_number >= MANIM_MAX_RETRIES (3) ise:
     - qa_correction_loop yerine dead_letter_queue_ravel'e yaz.
  4. Başarılıysa:
     - MinIO'ya yükle → presigned URL al
     - video_ready_events'e VideoReadyEvent yaz
     - Geçici mp4'ü temizle
"""
import asyncio
import logging
import signal
from datetime import datetime, timezone
from typing import Any

from .config import Settings, get_settings
from .kafka_io import KafkaConsumer, KafkaProducer, ensure_topics
from .minio_io import MinIOClient
from .renderer import ManimRenderer, RenderError
from .sandbox import SandboxValidator, ValidationResult
from .schemas import (
    DLQEvent,
    ManimRenderTask,
    QACorrectionRequest,
    VideoReadyEvent,
)

logger = logging.getLogger("manim_worker")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# ─── Health TCP ────────────────────────────────────────────────────

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


# ─── Pipeline ──────────────────────────────────────────────────────

class WorkerPipeline:
    """Bir task'ı sandbox → render → upload → publish akışından geçirir."""

    def __init__(
        self,
        settings: Settings,
        sandbox: SandboxValidator,
        renderer: ManimRenderer,
        minio: MinIOClient,
        producer: KafkaProducer,
    ):
        self.settings = settings
        self.sandbox = sandbox
        self.renderer = renderer
        self.minio = minio
        self.producer = producer

    async def handle(self, raw: dict) -> None:
        try:
            task = ManimRenderTask(**raw)
        except Exception:
            logger.exception("invalid ManimRenderTask payload: %s", raw)
            return

        logger.info(
            "[%s] task=%s attempt=%d quality=%s student=%s",
            task.trace_id, task.task_id, task.attempt_number,
            task.render_quality, task.student_id,
        )

        # 1) Sandbox
        result: ValidationResult = self.sandbox.validate(task.manim_code)
        if not result.is_valid:
            logger.warning(
                "[%s] sandbox rejected: type=%s msg=%s",
                task.trace_id, result.error_type, result.error_message,
            )
            await self._fail(
                task,
                error_type=result.error_type or "AST_VIOLATION",
                error_message=result.error_message or "sandbox rejected",
                traceback_snippet=result.traceback_snippet,
            )
            return

        # 2) Render — subprocess loop'u bloklamasın diye executor'da.
        # Sandbox temizlenmiş kodu cleaned_code'a koydu (markdown fence varsa
        # strip edildi); render her zaman temiz kodu kullansın.
        rendered_code = result.cleaned_code or task.manim_code
        loop = asyncio.get_running_loop()
        try:
            render_result = await loop.run_in_executor(
                None,
                self.renderer.render,
                rendered_code,
                task.task_id,
                task.render_quality,
                task.timeout_seconds,
            )
        except RenderError as e:
            err_type = "TIMEOUT" if e.is_timeout else "RENDER_ERROR"
            # traceback_snippet stderr/stdout'un son 500 byte'ını içeriyor —
            # gerçek nedeni (örn. AttributeError, NameError, LaTeX missing)
            # görmek için log'a ekliyoruz.
            snippet = (e.traceback_snippet or "")[-800:].replace("\n", " | ")
            logger.warning(
                "[%s] render failed: type=%s msg=%s detail=%s",
                task.trace_id, err_type, e.message, snippet,
            )
            await self._fail(
                task,
                error_type=err_type,
                error_message=e.message,
                traceback_snippet=e.traceback_snippet,
            )
            return
        except Exception as e:
            logger.exception("[%s] render unexpected error", task.trace_id)
            await self._fail(
                task,
                error_type="UNKNOWN",
                error_message=f"unexpected error: {type(e).__name__}: {e}",
                traceback_snippet=None,
            )
            return

        # 3) Upload
        try:
            video_url = await self.minio.upload_video(render_result.mp4_path, task.task_id)
        except Exception as e:
            logger.exception("[%s] MinIO upload failed", task.trace_id)
            await self._fail(
                task,
                error_type="UNKNOWN",
                error_message=f"MinIO upload failed: {e}",
                traceback_snippet=None,
            )
            self.renderer.cleanup_mp4(render_result.mp4_path)
            return
        finally:
            # video_url alındı → mp4 artık gereksiz
            self.renderer.cleanup_mp4(render_result.mp4_path)

        # 4) Başarı: video_ready_events'e yaz
        evt = VideoReadyEvent(
            task_id=task.task_id,
            correlation_id=task.correlation_id,
            trace_id=task.trace_id,
            student_id=task.student_id,
            video_url=video_url,
            duration_seconds=render_result.duration_seconds,
            file_size_bytes=render_result.file_size_bytes,
            timestamp=_now_iso(),
        )
        await self.producer.send(
            self.settings.topic_video_ready_events,
            evt.model_dump(),
            key=task.student_id,
        )
        logger.info(
            "[%s] video_ready: task=%s url=...%s size=%dB duration=%.2fs",
            task.trace_id, task.task_id, video_url[-40:],
            render_result.file_size_bytes, render_result.duration_seconds,
        )

    async def _fail(
        self,
        task: ManimRenderTask,
        error_type: str,
        error_message: str,
        traceback_snippet: str | None,
    ) -> None:
        """Hata durumunda: ya qa_correction_loop'a düzeltme isteği,
        ya da DLQ (deneme limitini aştık)."""
        if task.attempt_number >= self.settings.manim_max_retries:
            dlq = DLQEvent(
                task_id=task.task_id,
                correlation_id=task.correlation_id,
                trace_id=task.trace_id,
                student_id=task.student_id,
                source_topic=self.settings.topic_manim_render_tasks,
                reason=f"max_retries_exhausted ({self.settings.manim_max_retries})",
                attempts=task.attempt_number,
                last_error_type=error_type,
                last_error_message=error_message,
                timestamp=_now_iso(),
            )
            await self.producer.send(
                self.settings.topic_dlq,
                dlq.model_dump(),
                key=task.student_id,
            )
            logger.error(
                "[%s] DLQ: task=%s attempts=%d last_err=%s",
                task.trace_id, task.task_id, task.attempt_number, error_type,
            )
            return

        # qa_correction_loop'a düzeltme isteği yolla; attempt_number AYNI kalır
        # (bu attempt'i oluşturan hatayı raporluyoruz). Orchestrator bir sonraki
        # render'ı +1 ile gönderecek.
        qa = QACorrectionRequest(
            task_id=task.task_id,
            correlation_id=task.correlation_id,
            trace_id=task.trace_id,
            student_id=task.student_id,
            manim_code=task.manim_code,
            error_type=error_type,                                     # type: ignore[arg-type]
            error_message=error_message,
            traceback_snippet=traceback_snippet,
            attempt_number=task.attempt_number,
        )
        await self.producer.send(
            self.settings.topic_qa_correction_loop,
            qa.model_dump(),
            key=task.student_id,
        )
        logger.info(
            "[%s] QA correction requested: task=%s attempt=%d/%d type=%s",
            task.trace_id, task.task_id, task.attempt_number,
            self.settings.manim_max_retries, error_type,
        )


# ─── Main ──────────────────────────────────────────────────────────

async def main() -> None:
    settings: Settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger.info("manim_worker starting")

    # ── Clients ───────────────────────────────────────────────────
    producer = KafkaProducer(settings.kafka_bootstrap_servers)
    minio = MinIOClient(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        bucket=settings.minio_bucket_videos,
        url_expiration_seconds=settings.video_url_expiration_seconds,
        public_url_prefix=settings.minio_public_url_prefix,
    )
    sandbox = SandboxValidator(
        allowed_imports=[s.strip() for s in settings.sandbox_allowed_imports.split(",")],
        syntax_timeout_seconds=settings.sandbox_syntax_check_timeout_seconds,
    )
    renderer = ManimRenderer(
        temp_dir=settings.manim_temp_dir,
        default_timeout_seconds=settings.manim_render_timeout_seconds,
    )

    # ── Topics ────────────────────────────────────────────────────
    await ensure_topics(
        settings.kafka_bootstrap_servers,
        topics=[
            settings.topic_manim_render_tasks,
            settings.topic_qa_correction_loop,
            settings.topic_video_ready_events,
            settings.topic_dlq,
        ],
        num_partitions=settings.kafka_topic_partitions,
        replication_factor=settings.kafka_topic_replication,
    )

    # ── Infra ─────────────────────────────────────────────────────
    await minio.start()
    await minio.ensure_bucket()
    await producer.start()

    pipeline = WorkerPipeline(settings, sandbox, renderer, minio, producer)

    # Manim Worker iki ayrı topic'ten input alır:
    #   - manim_render_tasks      (yeni task, attempt=1)
    #   - manim_render_tasks      (orchestrator düzeltilmiş kodu yine buraya yazar
    #                              — qa_correction_loop'u Orchestrator dinler)
    # Yani Manim Worker yalnızca manim_render_tasks'i tüketir.
    # qa_correction_loop'u dinleyen Orchestrator'dur (düzeltme tetikleyici).

    async def task_handler(topic: str, value: dict[str, Any]) -> None:
        await pipeline.handle(value)

    consumer = KafkaConsumer(
        settings.kafka_bootstrap_servers,
        topics=[settings.topic_manim_render_tasks],
        group_id=settings.manim_worker_group_id,
    )
    await consumer.start(task_handler)

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

    health_task = asyncio.create_task(_health_server(stop_event, settings.health_port))

    logger.info(
        "manim_worker ready (group=%s, max_retries=%d, render_timeout=%ds)",
        settings.manim_worker_group_id,
        settings.manim_max_retries,
        settings.manim_render_timeout_seconds,
    )

    await stop_event.wait()

    # ── Graceful shutdown (reverse) ───────────────────────────────
    logger.info("manim_worker shutting down")
    await consumer.stop()
    await producer.stop()
    await minio.stop()
    health_task.cancel()
    try:
        await health_task
    except asyncio.CancelledError:
        pass
    logger.info("manim_worker stopped")


if __name__ == "__main__":
    asyncio.run(main())
