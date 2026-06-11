"""Async circuit breaker for the RAG dependency.

Why not use pybreaker directly:
  pybreaker is sync at its core; its async support relies on adapters that
  vary across versions and don't compose cleanly with our request-response
  pattern (request to Kafka, await a Future). We implement a minimal FSM
  here for predictable, version-agnostic behavior.

  pybreaker is kept in requirements.txt as a concept dependency for the
  team — when a synchronous external call (e.g. an HTTP plugin webhook)
  is added later, that one CAN use pybreaker's decorator directly.

State machine:
    closed → (fail_max consecutive failures) → open
    open   → (after reset_timeout seconds)    → half_open
    half_open → success → closed | failure → open (1 failure trips it)
"""
import asyncio
import logging
import time
from enum import Enum
from typing import Awaitable, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(Exception):
    """Raised when call() is invoked while the breaker is OPEN."""


class RAGCircuitBreaker:
    def __init__(
        self,
        fail_max: int = 5,
        reset_timeout: int = 60,
        fallback_text: str = "",
        name: str = "rag",
    ):
        self.name = name
        self.fail_max = fail_max
        self.reset_timeout = reset_timeout
        self.fallback_text = fallback_text

        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._opened_at: float | None = None
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        return self._state

    @property
    def is_open(self) -> bool:
        return self._state == CircuitState.OPEN

    async def call(self, fn: Callable[[], Awaitable[T]]) -> T:
        """Invoke fn() under breaker semantics. Pass a *factory* (zero-arg
        callable returning a coroutine) so we can re-execute on half-open.
        """
        async with self._lock:
            if self._state == CircuitState.OPEN:
                assert self._opened_at is not None
                if time.monotonic() - self._opened_at >= self.reset_timeout:
                    self._state = CircuitState.HALF_OPEN
                    logger.info("[%s] circuit half_open (probing)", self.name)
                else:
                    raise CircuitOpenError(f"{self.name} breaker open")

        try:
            result = await fn()
        except Exception:
            await self._record_failure()
            raise
        await self._record_success()
        return result

    async def _record_success(self) -> None:
        async with self._lock:
            if self._consecutive_failures or self._state != CircuitState.CLOSED:
                logger.info("[%s] circuit closed (success after %d failures)",
                            self.name, self._consecutive_failures)
            self._consecutive_failures = 0
            self._state = CircuitState.CLOSED
            self._opened_at = None

    async def _record_failure(self) -> None:
        async with self._lock:
            self._consecutive_failures += 1
            # half_open trips on a single failure; closed only after fail_max
            if self._state == CircuitState.HALF_OPEN or self._consecutive_failures >= self.fail_max:
                self._state = CircuitState.OPEN
                self._opened_at = time.monotonic()
                logger.warning("[%s] circuit OPEN (consecutive_failures=%d)",
                               self.name, self._consecutive_failures)
