"""Redis client for orchestrator — pending interaction state.

Modül 4'te anlatılan "gecikmeli ödül" akışı için: bir öğrenci yanıtı
işlendiğinde Bandit kararı + bağlam Redis'te bekletilir; sonraki
öğrenci yanıtı geldiğinde önceki bağlamla birleştirilip reward
hesaplanır.
"""
import json
import logging
from typing import Optional

from redis.asyncio import Redis

logger = logging.getLogger(__name__)


def _pending_key(student_id: str) -> str:
    return f"pending_interaction:{student_id}"


def _chat_key(student_id: str) -> str:
    return f"chat_history:{student_id}"


# Adım 7d: qa_dialog modu için son N mesajı tut (TTL 2 saat)
CONVERSATION_MAX_LEN = 10
CONVERSATION_TTL_SECONDS = 2 * 60 * 60


class RedisIO:
    def __init__(self, url: str):
        self._url = url
        self._client: Optional[Redis] = None

    async def start(self) -> None:
        self._client = Redis.from_url(self._url, decode_responses=True)
        await self._client.ping()

    async def stop(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> Redis:
        if self._client is None:
            raise RuntimeError("RedisIO not started")
        return self._client

    async def set_pending_interaction(self, student_id: str, data: dict, ttl: int) -> None:
        await self.client.set(_pending_key(student_id), json.dumps(data), ex=ttl)

    async def pop_pending_interaction(self, student_id: str) -> Optional[dict]:
        """Atomically read and delete the pending entry."""
        key = _pending_key(student_id)
        async with self.client.pipeline(transaction=True) as pipe:
            pipe.get(key)
            pipe.delete(key)
            results = await pipe.execute()
        raw = results[0]
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("invalid JSON in pending_interaction:%s", student_id)
            return None

    # ─── Adım 7d: conversation history (qa_dialog) ───────────────────

    async def push_conversation(
        self,
        student_id: str,
        role: str,                    # "user" | "assistant"
        content: str,
        max_len: int = CONVERSATION_MAX_LEN,
        ttl: int = CONVERSATION_TTL_SECONDS,
    ) -> None:
        """LPUSH + LTRIM + EXPIRE ile son `max_len` mesajı tut."""
        key = _chat_key(student_id)
        msg = json.dumps({"role": role, "content": content})
        async with self.client.pipeline(transaction=True) as pipe:
            pipe.lpush(key, msg)
            pipe.ltrim(key, 0, max_len - 1)
            pipe.expire(key, ttl)
            await pipe.execute()

    async def get_conversation(self, student_id: str) -> list[dict]:
        """En eski → en yeni sırasıyla son N mesaj. Bozuk JSON varsa atla."""
        raw = await self.client.lrange(_chat_key(student_id), 0, -1)
        out: list[dict] = []
        for item in reversed(raw):  # LRANGE en yeni başta; chrono için ters çevir
            try:
                out.append(json.loads(item))
            except json.JSONDecodeError:
                continue
        return out

    async def clear_conversation(self, student_id: str) -> None:
        await self.client.delete(_chat_key(student_id))
