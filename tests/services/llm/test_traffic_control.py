"""Tests for traffic control behavior."""

import pytest

from src.services.llm.traffic_control import TrafficController


@pytest.mark.asyncio
async def test_traffic_control_context() -> None:
    """Traffic control context manager should acquire and release slots."""
    controller = TrafficController(
        provider_name="test",
        max_concurrency=1,
        requests_per_minute=60,
    )

    async with controller:
        assert controller._semaphore.locked() is True

    assert controller._semaphore.locked() is False
