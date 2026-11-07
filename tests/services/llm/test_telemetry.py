"""Tests for telemetry decorator behavior."""

from _pytest.monkeypatch import MonkeyPatch
import pytest

from src.services.llm import telemetry


class _FakeLogger:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def debug(self, message: str, *args: object, **_kwargs: object) -> None:
        self.messages.append(message % args if args else message)

    def warning(self, message: str, *args: object, **_kwargs: object) -> None:
        self.messages.append(message % args if args else message)


@pytest.mark.asyncio
async def test_track_llm_call_success(monkeypatch: MonkeyPatch) -> None:
    """Successful calls should emit debug log entries."""
    fake_logger = _FakeLogger()
    monkeypatch.setattr(telemetry, "logger", fake_logger)

    @telemetry.track_llm_call("test")
    async def _func() -> str:
        return "ok"

    result = await _func()

    assert result == "ok"
    assert any("completed successfully" in msg for msg in fake_logger.messages)


@pytest.mark.asyncio
async def test_track_llm_call_failure(monkeypatch: MonkeyPatch) -> None:
    """Failures should emit warning log entries."""
    fake_logger = _FakeLogger()
    monkeypatch.setattr(telemetry, "logger", fake_logger)

    @telemetry.track_llm_call("test")
    async def _func() -> str:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await _func()

    assert any("failed" in msg for msg in fake_logger.messages)
