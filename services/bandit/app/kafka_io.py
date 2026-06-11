"""Kafka producer + consumer wrappers — same shape as gateway/orchestrator."""
import asyncio
import json
import logging
from typing import Awaitable, Callable, Optional

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from aiokafka.admin import AIOKafkaAdminClient, NewTopic
from aiokafka.errors import TopicAlreadyExistsError

logger = logging.getLogger(__name__)


class KafkaProducer:
    def __init__(self, bootstrap_servers: str):
        self._bootstrap = bootstrap_servers
        self._producer: Optional[AIOKafkaProducer] = None

    async def start(self) -> None:
        self._producer = AIOKafkaProducer(
            bootstrap_servers=self._bootstrap,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            acks="all",
        )
        await self._producer.start()

    async def stop(self) -> None:
        if self._producer is not None:
            await self._producer.stop()
            self._producer = None

    async def send(self, topic: str, value: dict, key: Optional[str] = None) -> None:
        if self._producer is None:
            raise RuntimeError("KafkaProducer not started")
        key_bytes = key.encode("utf-8") if key else None
        await self._producer.send_and_wait(topic, value=value, key=key_bytes)


class KafkaConsumer:
    def __init__(self, bootstrap_servers: str, topics: list[str], group_id: str):
        self._bootstrap = bootstrap_servers
        self._topics = topics
        self._group_id = group_id
        self._consumer: Optional[AIOKafkaConsumer] = None
        self._task: Optional[asyncio.Task] = None
        self._stopping = asyncio.Event()

    async def start(self, handler: Callable[[str, dict], Awaitable[None]]) -> None:
        self._consumer = AIOKafkaConsumer(
            *self._topics,
            bootstrap_servers=self._bootstrap,
            group_id=self._group_id,
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
            auto_offset_reset="latest",
            enable_auto_commit=True,
        )
        await self._consumer.start()
        self._task = asyncio.create_task(self._loop(handler))

    async def _loop(self, handler: Callable[[str, dict], Awaitable[None]]) -> None:
        assert self._consumer is not None
        try:
            async for msg in self._consumer:
                if self._stopping.is_set():
                    break
                try:
                    await handler(msg.topic, msg.value)
                except Exception:
                    logger.exception("handler failed: topic=%s offset=%d", msg.topic, msg.offset)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("consumer loop crashed")

    async def stop(self) -> None:
        self._stopping.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        if self._consumer is not None:
            await self._consumer.stop()
            self._consumer = None


async def ensure_topics(
    bootstrap_servers: str,
    topics: list[str],
    num_partitions: int,
    replication_factor: int,
) -> None:
    admin = AIOKafkaAdminClient(bootstrap_servers=bootstrap_servers)
    await admin.start()
    try:
        existing = set(await admin.list_topics())
        new = [
            NewTopic(name=t, num_partitions=num_partitions, replication_factor=replication_factor)
            for t in topics
            if t not in existing
        ]
        if not new:
            return
        try:
            await admin.create_topics(new)
            logger.info("created topics: %s", [t.name for t in new])
        except TopicAlreadyExistsError:
            pass
    finally:
        await admin.close()
