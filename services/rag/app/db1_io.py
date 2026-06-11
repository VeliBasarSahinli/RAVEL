"""DB-1 minimal asyncpg pool for RAG admin (Adım 7e).

RAG service yalnızca llm_configs CRUD yapacağı için Orchestrator'daki
DB1Client'ın sadece pool yönetimi kısmına ihtiyacı var. PgBouncer
transaction-pool tuzağı (ADR-011) — statement_cache_size=0 zorunlu.
"""
from __future__ import annotations

import logging
from typing import Optional

import asyncpg

logger = logging.getLogger(__name__)


class DB1Pool:
    def __init__(self, dsn: str, min_size: int = 1, max_size: int = 4):
        self._dsn = dsn
        self._min = min_size
        self._max = max_size
        self._pool: Optional[asyncpg.Pool] = None

    async def start(self) -> None:
        self._pool = await asyncpg.create_pool(
            dsn=self._dsn,
            min_size=self._min,
            max_size=self._max,
            command_timeout=10,
            statement_cache_size=0,         # ADR-011
        )

    async def stop(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    @property
    def pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("DB1Pool not started")
        return self._pool
