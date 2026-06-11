"""LearnerService — reward_logs_stream'i tüketir, ödülü hesaplar,
DB-2'ye INSERT yapar, mini-batch dolunca politika günceller, MinIO'ya
yazar, Redis Pub/Sub ile Actor'a sinyal yollar.
"""
import asyncio
import logging
import time
from typing import Optional

import numpy as np

from .config import Settings
from .db_io import DB2Client
from .lints import LinTS
from .minio_io import MinIOClient
from .redis_io import RedisIO
from .schemas import InteractionLogEntry, RewardLogEntry

logger = logging.getLogger(__name__)

ACTION_NAMES = ["text", "step_by_step", "video"]


class LearnerService:
    """Cold path: drink reward stream → recompute policy → publish."""

    def __init__(
        self,
        settings: Settings,
        db: DB2Client,
        minio: MinIOClient,
        redis_io: RedisIO,
    ):
        self.settings = settings
        self.db = db
        self.minio = minio
        self.redis_io = redis_io
        self._lints: Optional[LinTS] = None
        self._pending: list[tuple[np.ndarray, int, float]] = []
        self._buffer_lock = asyncio.Lock()
        self._last_flush_at = time.monotonic()
        self._timer_task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        loaded = await self.minio.load_weights()
        if loaded is None:
            self._lints = LinTS(
                n_actions=self.settings.bandit_num_actions,
                context_dim=self.settings.bandit_context_dim,
                alpha=self.settings.bandit_alpha,
            )
            logger.info("Learner: cold-start LinTS")
        else:
            self._lints = LinTS.from_dict(loaded)
            logger.info("Learner: loaded weights from MinIO")

        self._timer_task = asyncio.create_task(self._timer_flush_loop())

    async def stop(self) -> None:
        self._stop_event.set()
        if self._timer_task is not None:
            self._timer_task.cancel()
            try:
                await self._timer_task
            except (asyncio.CancelledError, Exception):
                pass

    async def _timer_flush_loop(self) -> None:
        """Eğer mini_batch_size'a ulaşılmadan TIMEOUT geçtiyse zorla flush."""
        try:
            while not self._stop_event.is_set():
                await asyncio.sleep(5)
                async with self._buffer_lock:
                    if not self._pending:
                        self._last_flush_at = time.monotonic()
                        continue
                    elapsed = time.monotonic() - self._last_flush_at
                    if elapsed >= self.settings.bandit_mini_batch_timeout_seconds:
                        logger.info(
                            "Learner: timer-triggered flush (elapsed=%.0fs, batch=%d)",
                            elapsed, len(self._pending),
                        )
                        await self._flush_locked()
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Learner: timer loop crashed")

    # ─── Reward formula ─────────────────────────────────────────────
    def compute_reward(self, entry: RewardLogEntry) -> float:
        """r_t = α·C_t + β·(T_baseline / T_actual) + γ·S_t

        T_actual ≤ 0 ise güvenli fallback (-1.0). T_baseline/T_actual oranı
        config'teki cap ile sınırlanır (T_actual çok küçükse uçuşmasın).
        """
        if entry.t_actual <= 0:
            logger.warning("[%s] T_actual=%.3f <= 0; using safe fallback reward=-1.0",
                           entry.trace_id, entry.t_actual)
            return -1.0

        time_efficiency = entry.t_baseline / entry.t_actual
        time_efficiency = min(time_efficiency, self.settings.reward_time_efficiency_cap)

        reward = (
            self.settings.reward_alpha * entry.c_t
            + self.settings.reward_beta * time_efficiency
            + self.settings.reward_gamma * entry.s_t
        )
        return float(reward)

    # ─── Reward handler ─────────────────────────────────────────────
    async def handle_reward(self, raw_msg: dict) -> None:
        try:
            entry = RewardLogEntry(**raw_msg)
        except Exception:
            logger.exception("Learner: invalid reward entry: %s", raw_msg)
            return

        # 1) reward'ı hesapla
        reward = self.compute_reward(entry)

        # 2) DB-2'ye INSERT (append-only, ravel_app role)
        try:
            log_entry = InteractionLogEntry(
                student_id=entry.student_id,
                topic_id=entry.topic_id,
                taxonomic_level=entry.taxonomic_level,
                action_taken=ACTION_NAMES[entry.action_taken],
                is_correct=entry.is_correct,
                time_spent_seconds=int(max(entry.t_actual, 0)),
                frustration_index=entry.frustration_index,
                reward_signal=reward,
            )
            await self.db.insert_interaction_log(log_entry)
            logger.info(
                "[%s] inserted interaction_log (reward=%.3f, action=%s)",
                entry.trace_id, reward, ACTION_NAMES[entry.action_taken],
            )
        except Exception:
            logger.exception("[%s] DB-2 insert failed", entry.trace_id)

        # 3) Mini-batch havuzuna ekle, eşik dolduysa flush et
        ctx = np.asarray(entry.context_vector, dtype=np.float64)
        if ctx.shape != (self.settings.bandit_context_dim,):
            logger.warning(
                "[%s] reward context shape %s != %d; skipping policy update",
                entry.trace_id, ctx.shape, self.settings.bandit_context_dim,
            )
            return

        async with self._buffer_lock:
            self._pending.append((ctx, entry.action_taken, reward))
            if len(self._pending) >= self.settings.bandit_mini_batch_size:
                logger.info("Learner: size-triggered flush (batch=%d)", len(self._pending))
                await self._flush_locked()

    # ─── Mini-batch flush (caller MUST hold _buffer_lock) ──────────
    async def _flush_locked(self) -> None:
        if not self._pending:
            return
        batch = self._pending
        self._pending = []
        self._last_flush_at = time.monotonic()

        # Online Bayesian update for each sample in the batch
        assert self._lints is not None
        for ctx, action, reward in batch:
            try:
                self._lints.update(ctx, action, reward)
            except Exception:
                logger.exception("Learner: update failed for action=%d reward=%.3f", action, reward)

        # Persist + signal — eğer MinIO yazımı veya Redis publish başarısız
        # olursa burada exception yutmuyoruz; restart sonrası en son
        # MinIO state'inden devam edilebilir.
        try:
            await self.minio.save_weights(self._lints.to_dict())
            await self.redis_io.publish_weight_update()
            logger.info("Learner: policy updated, weights persisted (batch_size=%d)", len(batch))
        except Exception:
            logger.exception("Learner: failed to persist weights / signal hot-swap")
