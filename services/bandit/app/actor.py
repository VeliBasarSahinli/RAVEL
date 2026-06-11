"""ActorService — bandit_decision_requests'i tüketir, <50ms'de karar verir,
bandit_decision_responses'a yazar. MinIO'dan sıcak ağırlık değişimi
(hot-swap) Redis Pub/Sub ile gelir.
"""
import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Optional

import numpy as np

from .config import Settings
from .kafka_io import KafkaProducer
from .lints import LinTS
from .minio_io import MinIOClient
from .redis_io import RedisIO
from .schemas import (
    BanditDecisionPayload,
    BanditDecisionRequest,
    BanditDecisionResponse,
)

logger = logging.getLogger(__name__)

ACTION_NAMES = ["text", "step_by_step", "video"]
ACTION_INDEX = {name: i for i, name in enumerate(ACTION_NAMES)}
# `manim_video` Adım 6 spec'inde bir alias olarak geçti — production'da
# kullanılmaz, yalnızca test override'ında kabul edilir.
_FORCE_ALIASES = {"manim_video": "video"}
ALLOWED_FORCE_VALUES = set(ACTION_INDEX.keys()) | set(_FORCE_ALIASES.keys())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class ActorService:
    """Hot path: read context → sample → write decision.

    Holds its OWN LinTS instance loaded from MinIO (no shared object with
    Learner — they communicate only via MinIO + Redis Pub/Sub, per spec).
    """

    def __init__(
        self,
        settings: Settings,
        producer: KafkaProducer,
        minio: MinIOClient,
        redis_io: RedisIO,
    ):
        self.settings = settings
        self.producer = producer
        self.minio = minio
        self.redis_io = redis_io
        self._lints: Optional[LinTS] = None
        self._swap_lock = asyncio.Lock()
        self._watcher_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        loaded = await self.minio.load_weights()
        if loaded is None:
            self._lints = LinTS(
                n_actions=self.settings.bandit_num_actions,
                context_dim=self.settings.bandit_context_dim,
                alpha=self.settings.bandit_alpha,
            )
            logger.info("Actor: cold-start LinTS (no weights in MinIO)")
        else:
            self._lints = LinTS.from_dict(loaded)
            logger.info("Actor: loaded weights from MinIO (n_actions=%d, dim=%d)",
                        self._lints.n_actions, self._lints.context_dim)

        self._watcher_task = asyncio.create_task(self._watch_weight_updates())

    async def stop(self) -> None:
        if self._watcher_task is not None:
            self._watcher_task.cancel()
            try:
                await self._watcher_task
            except (asyncio.CancelledError, Exception):
                pass

    async def _watch_weight_updates(self) -> None:
        """Hot-swap: yeni ağırlık sinyali gelince MinIO'dan oku, atomic swap."""
        try:
            async for version in self.redis_io.subscribe_weight_updates():
                logger.info("Actor: received weight update signal (version=%s)", version)
                try:
                    new_weights = await self.minio.load_weights()
                    if new_weights is None:
                        logger.warning("Actor: MinIO has no weights — keeping current")
                        continue
                    new_lints = LinTS.from_dict(new_weights)
                    async with self._swap_lock:
                        self._lints = new_lints
                    logger.info("Actor: weights hot-swapped successfully")
                except Exception:
                    logger.exception("Actor: weight reload failed (keeping current model)")
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Actor: watcher loop crashed")

    async def handle_request(self, raw_msg: dict) -> None:
        try:
            req = BanditDecisionRequest(**raw_msg)
        except Exception:
            logger.exception("Actor: invalid request payload: %s", raw_msg)
            return

        start = time.perf_counter()

        # Validate context vector size
        expected = self.settings.bandit_context_dim
        if len(req.context_vector) != expected:
            logger.warning(
                "[%s] invalid context_vector size %d (expected %d) — using neutral fallback",
                req.trace_id, len(req.context_vector), expected,
            )
            ctx = np.full(expected, 0.5, dtype=np.float64)
        else:
            ctx = np.asarray(req.context_vector, dtype=np.float64)

        # Test override — LinTS sampling'i bypass et (ADR-017).
        force_raw = (self.settings.bandit_force_decision or "").strip()
        force = _FORCE_ALIASES.get(force_raw, force_raw)
        if force and force in ACTION_INDEX:
            action_idx = ACTION_INDEX[force]
            confidence = 1.0
            logger.warning(
                "[%s] FORCED decision=%s (BANDIT_FORCE_DECISION override active)",
                req.trace_id, force,
            )
        else:
            async with self._swap_lock:
                assert self._lints is not None
                action_idx, confidence = self._lints.select_action(ctx)

        elapsed_ms = (time.perf_counter() - start) * 1000.0

        if elapsed_ms > self.settings.actor_inference_timeout_ms:
            logger.warning(
                "[%s] SLA breach: inference_ms=%.2f > %d action=%s",
                req.trace_id, elapsed_ms,
                self.settings.actor_inference_timeout_ms,
                ACTION_NAMES[action_idx],
            )
        else:
            logger.info(
                "[%s] inference_ms=%.2f action=%s confidence=%.3f",
                req.trace_id, elapsed_ms, ACTION_NAMES[action_idx], confidence,
            )

        # difficulty_adjustment: bu adımda Bandit henüz seviye geçişi
        # yapmıyor — sabit "B1". Adım 5+'da context vector seviyeyi
        # de etkileyecek şekilde genişletilebilir.
        response = BanditDecisionResponse(
            correlation_id=req.correlation_id,
            trace_id=req.trace_id,
            student_id=req.student_id,
            decision=BanditDecisionPayload(
                intervention_type=ACTION_NAMES[action_idx],
                difficulty_adjustment="B1",
                confidence_score=confidence,
            ),
            timestamp=_now_iso(),
        )
        await self.producer.send(
            self.settings.topic_bandit_decision_responses,
            response.model_dump(),
            key=req.student_id,
        )
