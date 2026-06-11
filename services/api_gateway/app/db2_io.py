"""DB-2 read-only client for API Gateway (Adım 8g — gamification stats).

XP / streak / badge hesaplama: interaction_logs üzerinden derive. Append-only
DB-2'den yalnızca SELECT yapıyoruz (ravel_app rolü zaten read-grant'lı).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import asyncpg

logger = logging.getLogger(__name__)

# Adım 8g: doğru cevap başına 15 XP (spec'ten)
XP_PER_CORRECT = 15
# İpuçlu doğru: 8 XP (action == 'text' veya 'step_by_step' olanlar)
XP_PER_HINTED_CORRECT = 8


class DB2ReadClient:
    def __init__(self, dsn: str, min_size: int = 1, max_size: int = 4):
        self._dsn = dsn
        self._pool: Optional[asyncpg.Pool] = None
        self._min = min_size
        self._max = max_size

    async def start(self) -> None:
        self._pool = await asyncpg.create_pool(
            dsn=self._dsn,
            min_size=self._min,
            max_size=self._max,
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

    async def gamification_stats(self, student_id: str) -> dict:
        """XP toplam (all-time), today_correct (TR günü), streak (60 günlük).

        Tek CTE'de 4 alt-aggregation:
          - all_time   : XP hesabı için tüm interaction sayımları
          - today      : Europe/Istanbul gününe göre bugünkü doğru
          - streak_arr : son 60 günün local distinct correct günleri (array)

        TZ: `timestamp` UTC'de saklanıyor; AT TIME ZONE 'UTC' AT TIME
        ZONE 'Europe/Istanbul' ile yerel güne çevirilir. Türkiye gece
        saatlerinde streak/today doğru hesaplanır.
        """
        row = await self.pool.fetchrow(
            """
            WITH all_time AS (
                SELECT
                    COUNT(*) FILTER (WHERE is_correct AND action_taken = 'text')         AS hinted_text,
                    COUNT(*) FILTER (WHERE is_correct AND action_taken = 'step_by_step') AS hinted_step,
                    COUNT(*) FILTER (WHERE is_correct)                                   AS correct_total,
                    COUNT(*)                                                             AS total
                FROM interaction_logs
                WHERE student_id = $1
            ),
            base AS (
                SELECT
                    is_correct,
                    (("timestamp" AT TIME ZONE 'UTC') AT TIME ZONE 'Europe/Istanbul')::date AS local_d
                FROM interaction_logs
                WHERE student_id = $1
                  AND "timestamp" >= NOW() - INTERVAL '60 days'
            ),
            today AS (
                SELECT COUNT(*) AS cnt
                FROM base
                WHERE is_correct
                  AND local_d = ((NOW() AT TIME ZONE 'Europe/Istanbul')::date)
            ),
            streak_days AS (
                SELECT DISTINCT local_d AS d
                FROM base
                WHERE is_correct
            )
            SELECT
                a.hinted_text, a.hinted_step, a.correct_total, a.total,
                t.cnt AS today_correct,
                COALESCE(
                    (SELECT array_agg(d ORDER BY d DESC) FROM streak_days),
                    ARRAY[]::date[]
                ) AS streak_dates
            FROM all_time a, today t
            """,
            student_id,
        )

        correct_total = int(row["correct_total"] or 0)
        total = int(row["total"] or 0)
        hinted = int(row["hinted_text"] or 0) + int(row["hinted_step"] or 0)
        direct = correct_total - hinted
        xp = direct * XP_PER_CORRECT + hinted * XP_PER_HINTED_CORRECT
        today_correct = int(row["today_correct"] or 0)

        # Streak (mevcut Python loop mantığı): bugünden geriye doğru
        # ardışık correct günleri say. Bugün yoksa dünden başla.
        day_set = {d for d in (row["streak_dates"] or [])}
        # NOW() AT TIME ZONE 'Europe/Istanbul' ≈ TR günü; Python tarafında
        # UTC date'ten saat 00-03 arasında 1 gün sapma olur, ama günler
        # set'ten kontrol edildiği için tutarlı (TR gününe göre yazıldı).
        cursor: date = (datetime.now(timezone.utc).astimezone().date()
                        if False else datetime.now(timezone.utc).date())
        # Daha doğru: TR offset'i hesapla — pytz olmadan +03:00 sabit
        tr_now = datetime.now(timezone.utc) + timedelta(hours=3)
        cursor = tr_now.date()
        if cursor not in day_set:
            cursor -= timedelta(days=1)
        streak = 0
        while cursor in day_set:
            streak += 1
            cursor -= timedelta(days=1)

        return {
            "xp": int(xp),
            "today_correct": today_correct,
            "correct_total": correct_total,
            "total_attempts": total,
            "streak": streak,
            "success_rate": round(correct_total / total, 2) if total else 0.0,
        }
