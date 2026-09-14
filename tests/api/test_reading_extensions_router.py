"""Router-level tests for the reading extension dispatch (#1448).

Under uvloop, ``loop.run_in_executor`` rejects a coroutine function outright —
every async ``run_action`` extension 503'd on the upload loop while the one
sync extension (read aloud) worked. The dispatch must branch on the handler
being a coroutine function: async handlers run on the loop, sync handlers keep
their private worker thread.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import inspect
from types import SimpleNamespace
from typing import Any

import pytest

from deeptutor.api.routers import reading_extensions as router_mod
from deeptutor.reading.extensions import ReadingExtensionManifest


def _manifest(extension_id: str, action_id: str) -> ReadingExtensionManifest:
    return ReadingExtensionManifest.model_validate(
        {
            "id": extension_id,
            "version": "1.0",
            "name": extension_id.title(),
            "actions": [{"id": action_id, "label": "Go"}],
            "result_types": ["card"],
        }
    )


def _card() -> dict[str, Any]:
    return {"type": "card", "title": "t", "message": "m"}


class _FakeStore:
    def unit_text(self, material_id: str, locator: int) -> str:
        return "some visible unit text"

    def position(self, material_id: str) -> SimpleNamespace:
        return SimpleNamespace(locator=1, source_anchor="anchor")


class _CountingExecutor:
    """Mimics uvloop's strict rejection of coroutines in run_in_executor."""

    def __init__(self) -> None:
        self._inner = ThreadPoolExecutor(max_workers=1)
        self.submit_calls = 0

    def submit(self, fn, /, *args, **kwargs):
        self.submit_calls += 1
        if inspect.iscoroutinefunction(fn) or inspect.iscoroutine(fn):
            raise TypeError("coroutines cannot be used with run_in_executor()")
        return self._inner.submit(fn, *args, **kwargs)


class _FakeRegistry:
    def __init__(self, extension: Any, executor: Any) -> None:
        self._extension = extension
        self._executor = executor

    def get(self, extension_id: str) -> Any:
        return self._extension if self._extension.manifest.id == extension_id else None

    def begin_action(self, extension_id: str) -> bool:
        return True

    def finish_action(self, extension_id: str) -> None:
        return None

    def mark_timed_out(self, extension_id: str) -> None:
        return None

    def executor_for(self, extension_id: str) -> Any:
        return self._executor


def _install(monkeypatch: pytest.MonkeyPatch, registry: _FakeRegistry) -> None:
    monkeypatch.setattr(router_mod, "assert_learning_material", lambda _material_id: None)
    monkeypatch.setattr(router_mod, "allowed_reading_extensions", lambda: None)
    monkeypatch.setattr(router_mod, "get_reading_extension_registry", lambda: registry)
    monkeypatch.setattr(router_mod, "ReadingStore", _FakeStore)


def _payload() -> router_mod.ActionPayload:
    return router_mod.ActionPayload(locator=1, selection="", locale="en")


@pytest.mark.asyncio
async def test_async_extension_runs_on_the_loop_under_a_strict_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An async run_action must not go through run_in_executor.

    uvloop rejects the coroutine a worker-thread call returns, so every
    LLM-backed reading extension 503'd on the upload turn while the sync
    read-aloud extension worked (#1448).
    """
    executor = _CountingExecutor()

    class VocabularyExtension:
        manifest = _manifest("vocabulary", "explain")

        async def run_action(self, action: str, context: Any) -> dict[str, Any]:
            return _card()

    _install(monkeypatch, _FakeRegistry(VocabularyExtension(), executor))

    result = await router_mod.run_extension_action("mat-1", "vocabulary", "explain", _payload())

    assert result["type"] == "card"
    # The async handler never touched the executor at all.
    assert executor.submit_calls == 0


@pytest.mark.asyncio
async def test_sync_extension_still_runs_in_its_worker_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor = _CountingExecutor()

    class ReadAloudExtension:
        manifest = ReadingExtensionManifest.model_validate(
            {
                "id": "read_aloud",
                "version": "1.0",
                "name": "Read Aloud",
                "actions": [{"id": "read", "label": "Go"}],
                "result_types": ["browser_speech"],
            }
        )

        def run_action(self, action: str, context: Any) -> dict[str, Any]:
            return {"type": "browser_speech", "payload": {"text": "hello"}}

    _install(monkeypatch, _FakeRegistry(ReadAloudExtension(), executor))

    result = await router_mod.run_extension_action("mat-1", "read_aloud", "read", _payload())

    assert result["type"] == "browser_speech"
    assert executor.submit_calls == 1


@pytest.mark.asyncio
async def test_async_extension_still_works_on_a_lenient_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The stock loop tolerated the old coroutine-object roundtrip; the fix
    must not regress deployments on it."""
    executor = ThreadPoolExecutor(max_workers=1)

    class QuizExtension:
        manifest = _manifest("quiz", "start")

        async def run_action(self, action: str, context: Any) -> dict[str, Any]:
            return _card()

    _install(monkeypatch, _FakeRegistry(QuizExtension(), executor))

    result = await router_mod.run_extension_action("mat-1", "quiz", "start", _payload())

    assert result["type"] == "card"
