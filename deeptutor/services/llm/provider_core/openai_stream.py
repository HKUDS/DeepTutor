"""Own the HTTP response behind a provider's OpenAI SDK stream."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import logging
from typing import Any

logger = logging.getLogger(__name__)


@asynccontextmanager
async def managed_openai_stream(stream: Any) -> AsyncIterator[Any]:
    """Close the response even when a callback fails outside the SDK iterator."""
    try:
        yield stream
    finally:
        close = getattr(stream, "close", None)
        if callable(close):
            try:
                await close()
            except Exception as exc:
                # Cleanup must not replace a provider/callback error or cancellation.
                logger.warning("OpenAI stream cleanup failed (%s)", type(exc).__name__)
