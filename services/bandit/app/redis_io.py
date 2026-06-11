"""Redis Pub/Sub wrapper for hot-swap signaling."""
import logging
from typing import AsyncIterator, Optional

from redis.asyncio import Redis

logger = logging.getLogger(__name__)

WEIGHT_UPDATE_CHANNEL = "bandit:weights:updated"


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

    async def publish_weight_update(self, version: str = "latest") -> None:
        await self.client.publish(WEIGHT_UPDATE_CHANNEL, version)
        logger.info("Redis: published weight update signal (version=%s)", version)

    async def subscribe_weight_updates(self) -> AsyncIterator[str]:
        """Yield each notification message body."""
        pubsub = self.client.pubsub()
        await pubsub.subscribe(WEIGHT_UPDATE_CHANNEL)
        try:
            async for msg in pubsub.listen():
                if msg.get("type") == "message":
                    yield str(msg.get("data", ""))
        finally:
            try:
                await pubsub.unsubscribe(WEIGHT_UPDATE_CHANNEL)
                await pubsub.aclose()
            except Exception:
                pass
