"""DB-2 read-only client for Orchestrator (Adım 7d).

Bandit Learner DB-2'ye INSERT yapıyor (Adım 4). Adım 7'de Orchestrator
prompt context için DB-2'den iki türetilmiş istatistik istiyor:

  - consecutive_errors(student_id, topic_id):
      Son etkileşim listesinde, baştan başlayan (en güncel ←) ardışık
      `is_correct=False AND topic_id=$2` zincirinin uzunluğu.

  - success_rate(student_id, topic_id):
      Son 20 etkileşim üzerinden, ilgili topic'te is_correct=True oranı
      (ya da topic'i hiç görmediyse None).

`ravel_app` rolü DB-2'ye SELECT yetkili (init_app_role.sh). UPDATE/DELETE
yok, sadece SELECT — yine de prompt context'ten emin olmak için.

Hata izolasyonu: DB-2 down ise stats() (None, None) döndürür; workflow
prompt context'inde 0 / 0.0 default'larla devam eder.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import asyncpg

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StudentTopicStats:
    consecutive_errors: int
    success_rate: float            # 0.0–1.0; topic veri yoksa 0.0


class DB2ReadClient:
    def __init__(self, dsn: str, min_size: int = 1, max_size: int = 4):
        self._dsn = dsn
        self._min_size = min_size
        self._max_size = max_size
        self._pool: Optional[asyncpg.Pool] = None

    async def start(self) -> None:
        # PgBouncer transaction-pool tuzağı (ADR-011) — statement_cache_size=0 zorunlu.
        self._pool = await asyncpg.create_pool(
            dsn=self._dsn,
            min_size=self._min_size,
            max_size=self._max_size,
            command_timeout=5,
            statement_cache_size=0,
        )

    async def stop(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    @property
    def pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("DB2ReadClient not started")
        return self._pool

    async def stats(self, student_id: str, topic_id: str) -> StudentTopicStats:
        """Topic'e dair son etkileşim istatistikleri.

        Sorgular son 20 kayıtla sınırlı tutulur (büyük öğrenci geçmişlerinde
        plan stabil); index `interaction_logs_student_time_idx` kullanılır.
        """
        # consecutive_errors: en güncelden başlayarak topic eşleşen kayıtları
        # gez, ilk is_correct=True'da kır.
        rows = await self.pool.fetch(
            """
            SELECT topic_id, is_correct
              FROM interaction_logs
             WHERE student_id = $1
             ORDER BY "timestamp" DESC
             LIMIT 20
            """,
            student_id,
        )
        cons_err = 0
        for r in rows:
            if r["topic_id"] != topic_id:
                continue
            if r["is_correct"]:
                break
            cons_err += 1

        # success_rate: son 20 etkileşimde topic eşleşen kayıtlar üzerinden
        topic_rows = [r for r in rows if r["topic_id"] == topic_id]
        if not topic_rows:
            success = 0.0
        else:
            success = sum(1 for r in topic_rows if r["is_correct"]) / len(topic_rows)

        return StudentTopicStats(consecutive_errors=cons_err, success_rate=success)
