import logging
from typing import Optional

import asyncpg

logger = logging.getLogger(__name__)


class DB1Client:
    """asyncpg pool wrapper for ravel_db1 (students table).

    Connects with the ravel_app role (Step 2b): SELECT, INSERT, UPDATE on
    students; DELETE is intentionally not granted.
    """

    def __init__(self, dsn: str, min_size: int = 2, max_size: int = 10):
        self._dsn = dsn
        self._min_size = min_size
        self._max_size = max_size
        self._pool: Optional[asyncpg.Pool] = None

    async def start(self) -> None:
        # statement_cache_size=0 is REQUIRED when going through PgBouncer in
        # transaction (or statement) pool mode: PgBouncer may route each
        # transaction to a different backend, so asyncpg's client-side
        # prepared-statement cache becomes inconsistent and you get
        # DuplicatePreparedStatementError on the second query onward.
        # See ADR-011 for the full incident.
        self._pool = await asyncpg.create_pool(
            dsn=self._dsn,
            min_size=self._min_size,
            max_size=self._max_size,
            command_timeout=10,
            statement_cache_size=0,
        )

    async def stop(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    @property
    def pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("DB1Client not started")
        return self._pool

    async def get_student_profile(self, student_id: str) -> Optional[dict]:
        """Return {grade_level, learning_style_vector} or None."""
        row = await self.pool.fetchrow(
            "SELECT grade_level, learning_style_vector FROM students WHERE student_id = $1",
            student_id,
        )
        if row is None:
            return None
        return {
            "grade_level": row["grade_level"],
            "learning_style_vector": list(row["learning_style_vector"]),
        }

    async def upsert_student(self, student_id: str, grade_level: int) -> None:
        """Create the student if missing; if present, leave intact (no UPDATE).

        UPDATE on grade_level is not part of this method's contract — Bandit
        is the only role permitted to mutate learning_style_vector elsewhere.
        """
        # ON CONFLICT DO NOTHING avoids UPDATE entirely (safe under ravel_app
        # privileges even if the role had no UPDATE — which it does, but we
        # don't lean on it here).
        await self.pool.execute(
            """
            INSERT INTO students (student_id, grade_level)
            VALUES ($1, $2)
            ON CONFLICT (student_id) DO NOTHING
            """,
            student_id,
            grade_level,
        )
