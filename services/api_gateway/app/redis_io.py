import json
from typing import Optional

from redis.asyncio import Redis


class RedisIO:
    """Thin wrapper around redis.asyncio with RAVEL-specific helpers."""

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

    # ── Session tracking (multi-Gateway aware) ──
    async def set_session(self, student_id: str, data: dict, ttl: int) -> None:
        await self.client.set(f"session:{student_id}", json.dumps(data), ex=ttl)

    async def delete_session(self, student_id: str) -> None:
        await self.client.delete(f"session:{student_id}")

    # ── Pending downstream messages (when student is offline) ──
    async def push_pending(self, student_id: str, payload_json: str, ttl: int) -> None:
        key = f"pending:{student_id}"
        async with self.client.pipeline(transaction=True) as pipe:
            pipe.rpush(key, payload_json)
            pipe.expire(key, ttl)
            await pipe.execute()

    async def drain_pending(self, student_id: str) -> list[str]:
        """Atomically read and clear the pending list."""
        key = f"pending:{student_id}"
        async with self.client.pipeline(transaction=True) as pipe:
            pipe.lrange(key, 0, -1)
            pipe.delete(key)
            results = await pipe.execute()
        return results[0] or []

    # ── Asked-questions set per (student, topic) ──
    # Aynı oturumda öğrenciye aynı soruyu tekrar göstermemek için.
    # TTL bir öğrenme oturumunu kapsar; süresi dolduğunda set silinir
    # ve öğrenci tüm soruları yeniden görebilir.
    @staticmethod
    def _asked_key(student_id: str, topic: str) -> str:
        return f"asked:{student_id}:{topic}"

    async def get_asked(self, student_id: str, topic: str) -> set[str]:
        members = await self.client.smembers(self._asked_key(student_id, topic))
        return set(members)

    async def add_asked(
        self, student_id: str, topic: str, question_id: str, ttl: int,
    ) -> None:
        key = self._asked_key(student_id, topic)
        async with self.client.pipeline(transaction=True) as pipe:
            pipe.sadd(key, question_id)
            pipe.expire(key, ttl)
            await pipe.execute()

    async def clear_asked(self, student_id: str, topic: str) -> None:
        await self.client.delete(self._asked_key(student_id, topic))

    # ── Chat history (qa_dialog Sokratik diyalog için) ──
    @staticmethod
    def _chat_key(student_id: str, topic: str) -> str:
        return f"chat:{student_id}:{topic}"

    async def append_chat_history(
        self, student_id: str, topic: str, role: str, message: str,
        max_turns: int = 10, ttl_seconds: int = 3600,
    ) -> None:
        """Chat geçmişine bir turn ekle. RPUSH + LTRIM ile son N*2 mesaj
        tutuluyor (her turn user+assistant); EXPIRE ile 1 saatlik TTL."""
        if not topic:
            return
        key = self._chat_key(student_id, topic)
        entry = json.dumps({"role": role, "content": (message or "")[:2000]})
        async with self.client.pipeline(transaction=True) as pipe:
            pipe.rpush(key, entry)
            pipe.ltrim(key, -(max_turns * 2), -1)
            pipe.expire(key, ttl_seconds)
            await pipe.execute()

    async def get_chat_history(self, student_id: str, topic: str) -> list[dict]:
        if not topic:
            return []
        key = self._chat_key(student_id, topic)
        entries = await self.client.lrange(key, 0, -1)
        out: list[dict] = []
        for e in entries:
            try:
                out.append(json.loads(e))
            except Exception:
                continue
        return out

    async def clear_chat_history(self, student_id: str, topic: str) -> None:
        if not topic:
            return
        await self.client.delete(self._chat_key(student_id, topic))
