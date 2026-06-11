import asyncio
import json
import logging

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Per-process registry of live WebSocket connections.

    A WebSocket can only be written to from the process that owns it,
    so this dict is unavoidable. For horizontal Gateway scaling we'd add
    a Redis Pub/Sub fan-out: every Gateway subscribes to a routing
    channel; whoever owns the target student's WebSocket picks the
    message up and writes it. NOT yet implemented.
    """

    def __init__(self) -> None:
        self._connections: dict[str, WebSocket] = {}
        self._lock = asyncio.Lock()

    async def connect(self, student_id: str, ws: WebSocket) -> None:
        async with self._lock:
            previous = self._connections.get(student_id)
            self._connections[student_id] = ws
        if previous is not None:
            try:
                await previous.close(code=1000, reason="superseded by new connection")
            except Exception:
                logger.debug("previous ws already closed for %s", student_id)

    async def disconnect(self, student_id: str, ws: WebSocket) -> None:
        async with self._lock:
            current = self._connections.get(student_id)
            if current is ws:
                self._connections.pop(student_id, None)

    async def send_to(self, student_id: str, message: dict) -> bool:
        ws = self._connections.get(student_id)
        if ws is None:
            return False
        try:
            await ws.send_text(json.dumps(message))
            return True
        except Exception:
            logger.exception("ws send failed for %s; dropping connection", student_id)
            await self.disconnect(student_id, ws)
            return False
