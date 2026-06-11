"""llm_configs CRUD over DB-1 (uses the same DB1Client.pool).

Caller is responsible for encrypting api_key BEFORE upsert (we accept
already-encrypted bytes here so the repo never sees plaintext).
Decryption is also done by the caller — repo just hands back the BYTEA.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import asyncpg

logger = logging.getLogger(__name__)


@dataclass
class LLMConfig:
    """Row from llm_configs. api_key_blob is the AES-GCM ciphertext (or None)."""
    config_id: str
    agent_name: str
    provider: str
    model_name: str
    api_key_blob: Optional[bytes]
    endpoint_url: Optional[str]
    max_tokens: int
    temperature: float
    is_active: bool


def _row_to_config(row: asyncpg.Record) -> LLMConfig:
    return LLMConfig(
        config_id=str(row["config_id"]),
        agent_name=row["agent_name"],
        provider=row["provider"],
        model_name=row["model_name"],
        api_key_blob=bytes(row["api_key"]) if row["api_key"] is not None else None,
        endpoint_url=row["endpoint_url"],
        max_tokens=row["max_tokens"],
        temperature=float(row["temperature"]),
        is_active=row["is_active"],
    )


class LLMConfigsRepo:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def get_active(self, agent_name: str) -> Optional[LLMConfig]:
        row = await self._pool.fetchrow(
            """
            SELECT config_id, agent_name, provider, model_name, api_key,
                   endpoint_url, max_tokens, temperature, is_active
              FROM llm_configs
             WHERE agent_name = $1 AND is_active = TRUE
            """,
            agent_name,
        )
        return _row_to_config(row) if row else None

    async def list_all(self) -> list[LLMConfig]:
        rows = await self._pool.fetch(
            """
            SELECT config_id, agent_name, provider, model_name, api_key,
                   endpoint_url, max_tokens, temperature, is_active
              FROM llm_configs
             ORDER BY agent_name
            """,
        )
        return [_row_to_config(r) for r in rows]

    async def upsert(
        self,
        agent_name: str,
        provider: str,
        model_name: str,
        api_key_blob: Optional[bytes],
        endpoint_url: Optional[str],
        max_tokens: int,
        temperature: float,
        is_active: bool = True,
    ) -> LLMConfig:
        """Insert if missing, otherwise UPDATE all mutable fields.

        Note: api_key_blob=None means "no key stored" (e.g. ollama). To
        leave an existing key untouched on update, callers must read the
        current row, keep the existing blob, and pass it back.
        """
        row = await self._pool.fetchrow(
            """
            INSERT INTO llm_configs
                   (agent_name, provider, model_name, api_key, endpoint_url,
                    max_tokens, temperature, is_active)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (agent_name) DO UPDATE SET
                provider     = EXCLUDED.provider,
                model_name   = EXCLUDED.model_name,
                api_key      = EXCLUDED.api_key,
                endpoint_url = EXCLUDED.endpoint_url,
                max_tokens   = EXCLUDED.max_tokens,
                temperature  = EXCLUDED.temperature,
                is_active    = EXCLUDED.is_active
            RETURNING config_id, agent_name, provider, model_name, api_key,
                      endpoint_url, max_tokens, temperature, is_active
            """,
            agent_name, provider, model_name, api_key_blob, endpoint_url,
            max_tokens, temperature, is_active,
        )
        return _row_to_config(row)

    async def update_partial(
        self,
        agent_name: str,
        *,
        provider: Optional[str] = None,
        model_name: Optional[str] = None,
        api_key_blob: Optional[bytes] = None,
        clear_api_key: bool = False,
        endpoint_url: Optional[str] = None,
        clear_endpoint: bool = False,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        is_active: Optional[bool] = None,
    ) -> Optional[LLMConfig]:
        """Patch existing row. Each field is None → unchanged.

        clear_api_key=True writes NULL (ollama transition).
        clear_endpoint=True writes NULL (managed-API transition).
        """
        sets: list[str] = []
        args: list = []
        i = 1

        def add(col: str, val):
            nonlocal i
            sets.append(f"{col} = ${i}")
            args.append(val)
            i += 1

        if provider is not None:    add("provider", provider)
        if model_name is not None:  add("model_name", model_name)
        if api_key_blob is not None:add("api_key", api_key_blob)
        elif clear_api_key:         add("api_key", None)
        if endpoint_url is not None:add("endpoint_url", endpoint_url)
        elif clear_endpoint:        add("endpoint_url", None)
        if max_tokens is not None:  add("max_tokens", max_tokens)
        if temperature is not None: add("temperature", temperature)
        if is_active is not None:   add("is_active", is_active)

        if not sets:
            return await self.get_active(agent_name) or None  # nothing to change

        args.append(agent_name)
        sql = f"""
            UPDATE llm_configs SET {", ".join(sets)}
             WHERE agent_name = ${i}
            RETURNING config_id, agent_name, provider, model_name, api_key,
                      endpoint_url, max_tokens, temperature, is_active
        """
        row = await self._pool.fetchrow(sql, *args)
        return _row_to_config(row) if row else None

    async def delete(self, agent_name: str) -> bool:
        result = await self._pool.execute(
            "DELETE FROM llm_configs WHERE agent_name = $1",
            agent_name,
        )
        # asyncpg returns "DELETE N"
        try:
            return int(result.split()[-1]) > 0
        except Exception:
            return False
