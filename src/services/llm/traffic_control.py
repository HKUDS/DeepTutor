"""Traffic control primitives for LLM providers."""

from __future__ import annotations

import asyncio
import time
from types import TracebackType

from src.logging import get_logger

logger = get_logger(__name__)


class TrafficController:
    """
    Controls concurrency and rate limits for LLM providers.

    Protects both the local system (resource exhaustion) and
    remote provider (rate limits).
    """

    def __init__(
        self,
        provider_name: str,
        max_concurrency: int = 20,
        requests_per_minute: int = 600,
        acquisition_timeout: float = 30.0,
    ) -> None:
        """
        Args:
            provider_name: Label for logging.
            max_concurrency: Max simultaneous in-flight requests (bulkheads).
            requests_per_minute: Max RPM allowed before local throttling.
            acquisition_timeout: Max seconds to wait for a slot before failing.
        """
        self.provider_name = provider_name
        self.max_concurrency = max_concurrency
        if requests_per_minute <= 0:
            raise ValueError("requests_per_minute must be > 0")
        self.rpm = requests_per_minute
        self.acquisition_timeout = acquisition_timeout

        # Concurrency Gate
        self._semaphore = asyncio.Semaphore(max_concurrency)

        # Rate Limiting (Token Bucket)
        self._tokens = float(requests_per_minute)
        self._last_refill = time.monotonic()
        self._fill_rate = requests_per_minute / 60.0  # tokens per second
        self._lock = asyncio.Lock()  # Protects token state

    async def _wait_for_token(self) -> None:
        """Consumes a rate limit token, waiting if necessary."""
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill

            # Refill tokens
            new_tokens = elapsed * self._fill_rate
            if new_tokens > 0:
                self._tokens = min(float(self.rpm), self._tokens + new_tokens)
                self._last_refill = now

            # Consume token
            if self._tokens >= 1:
                self._tokens -= 1.0
                return

            # Calculate wait time needed for 1 token
            wait_time = (1.0 - self._tokens) / self._fill_rate

        # Wait outside lock to avoid blocking other tasks
        if wait_time > 0:
            logger.debug("[%s] Rate limit active, waiting %.2fs" % (self.provider_name, wait_time))
            await asyncio.sleep(wait_time)
            # Recursively try again (simplest way to ensure thread safety after sleep)
            await self._wait_for_token()

    async def __aenter__(self) -> TrafficController:
        """
        Acquire concurrency slot AND rate limit token.
        Raises asyncio.TimeoutError if system is overloaded.
        """
        start = time.monotonic()

        # 1. Acquire Concurrency Slot
        try:
            # wait_for adds a timeout to the semaphore acquisition
            await asyncio.wait_for(self._semaphore.acquire(), timeout=self.acquisition_timeout)
        except TimeoutError:
            logger.error(
                "[%s] Local concurrency limit (%s) exceeded for >%.1fs."
                % (self.provider_name, self.max_concurrency, self.acquisition_timeout)
            )
            raise

        # 2. Acquire Rate Limit Token (if we passed concurrency check)
        # Note: We do this AFTER semaphore to ensure we don't wait for tokens
        # while holding a concurrency slot if we don't have to,
        # BUT strictly speaking, holding the semaphore while waiting for rate limits
        # prevents queue jumping.
        try:
            await self._wait_for_token()
        except Exception:
            # If rate limiter fails/cancels, release semaphore
            self._semaphore.release()
            raise

        wait_duration = time.monotonic() - start
        if wait_duration > 1.0:
            logger.warning("[%s] Traffic control wait: %.2fs" % (self.provider_name, wait_duration))

        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Release concurrency slot."""
        self._semaphore.release()
        return None


__all__ = ["TrafficController"]
