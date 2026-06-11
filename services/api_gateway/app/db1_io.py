"""DB-1 client for API Gateway (Adım 8a).

Authentication-related queries: users (students table) lookup by
username, profile fetch by id, registration insert. PgBouncer
transaction-pool tuzağı (ADR-011) — statement_cache_size=0 zorunlu.
"""
from __future__ import annotations

import logging
from typing import Optional

import asyncpg

logger = logging.getLogger(__name__)


class DB1Client:
    def __init__(self, dsn: str, min_size: int = 1, max_size: int = 6):
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

    # ─── Auth queries ────────────────────────────────────────────────

    async def get_user_by_username(self, username: str) -> Optional[dict]:
        """Returns full row including password_hash for verification, or None."""
        row = await self.pool.fetchrow(
            """
            SELECT student_id, username, password_hash, role, grade_level, display_name
              FROM students
             WHERE username = $1
            """,
            username,
        )
        if row is None:
            return None
        return {
            "student_id": str(row["student_id"]),
            "username": row["username"],
            "password_hash": row["password_hash"],
            "role": row["role"],
            "grade_level": row["grade_level"],
            "display_name": row["display_name"],
        }

    async def get_profile(self, student_id: str) -> Optional[dict]:
        """For /auth/me + /api/profile — no password_hash returned."""
        row = await self.pool.fetchrow(
            """
            SELECT student_id, username, role, grade_level, display_name
              FROM students
             WHERE student_id = $1
            """,
            student_id,
        )
        if row is None:
            return None
        return {
            "student_id": str(row["student_id"]),
            "username": row["username"],
            "role": row["role"],
            "grade_level": row["grade_level"],
            "display_name": row["display_name"],
        }

    async def create_user(
        self,
        username: str,
        password_hash: str,
        grade_level: Optional[int],
        display_name: Optional[str],
        role: str = "student",
    ) -> Optional[dict]:
        """INSERT students; ON CONFLICT (username) → return None.
        Caller raises 409 in that case.

        Adım 8 ek not: grade_level None gelebilir → cold-start placeholder
        olarak 6 yazılır. Öğrenci sidebar'dan sınıf seçer; her interaction
        kendi grade_level'ını override eder.
        """
        gl = grade_level if grade_level is not None else 6
        row = await self.pool.fetchrow(
            """
            INSERT INTO students (username, password_hash, grade_level, display_name, role)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (username) WHERE username IS NOT NULL DO NOTHING
            RETURNING student_id
            """,
            username, password_hash, gl, display_name, role,
        )
        if row is None:
            return None
        return {"student_id": str(row["student_id"])}
