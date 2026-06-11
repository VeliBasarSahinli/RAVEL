"""DB-2 (ravel_db2) async client — append-only writes only.

ravel_app role grants on interaction_logs are SELECT + INSERT
(see ADR-007); UPDATE/DELETE will be rejected by Postgres at the
permission layer if accidentally attempted.

ADR-011 mandates statement_cache_size=0 for asyncpg through PgBouncer
in transaction pool mode.
"""
import logging
from typing import Optional

import asyncpg

from .schemas import InteractionLogEntry

logger = logging.getLogger(__name__)


class DB2Client:
    def __init__(self, dsn: str, min_size: int = 2, max_size: int = 10):
        self._dsn = dsn
        self._min_size = min_size
        self._max_size = max_size
        self._pool: Optional[asyncpg.Pool] = None

    async def start(self) -> None:
        self._pool = await asyncpg.create_pool(
            dsn=self._dsn,
            min_size=self._min_size,
            max_size=self._max_size,
            command_timeout=10,
            statement_cache_size=0,   # ADR-011: PgBouncer transaction-pool tuzağı
        )

    async def stop(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    @property
    def pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("DB2Client not started")
        return self._pool

    async def insert_interaction_log(self, entry: InteractionLogEntry) -> None:
        await self.pool.execute(
            """
            INSERT INTO interaction_logs
              (student_id, topic_id, taxonomic_level, action_taken,
               is_correct, time_spent_seconds, frustration_index, reward_signal)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
            entry.student_id,
            entry.topic_id,
            entry.taxonomic_level,
            entry.action_taken,
            entry.is_correct,
            entry.time_spent_seconds,
            entry.frustration_index,
            entry.reward_signal,
        )

    async def get_recent_interactions(self, student_id: str, limit: int = 50) -> list[dict]:
        """For Learner's policy update — chronological tail of a student's history."""
        rows = await self.pool.fetch(
            """
            SELECT student_id, topic_id, taxonomic_level, action_taken,
                   is_correct, time_spent_seconds, frustration_index,
                   reward_signal, "timestamp"
            FROM interaction_logs
            WHERE student_id = $1
            ORDER BY "timestamp" DESC
            LIMIT $2
            """,
            student_id,
            limit,
        )
        return [dict(r) for r in rows]
