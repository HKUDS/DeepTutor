from __future__ import annotations

from types import SimpleNamespace

import pytest

from deeptutor.api.routers import system as system_router
from deeptutor.runtime.memory_probe import MemorySnapshot, ProcessMemory


def _snapshot(*processes: ProcessMemory, **overrides: object) -> MemorySnapshot:
    fields: dict[str, object] = {
        "processes": processes,
        "total_rss_bytes": sum(p.rss_bytes for p in processes),
        "limit_bytes": 16 * 1024**3,
        "available_bytes": 8 * 1024**3,
        "limit_source": "host",
        "partial": False,
    }
    fields.update(overrides)
    return MemorySnapshot(**fields)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_embeddings_connection_uses_batch_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, list[str]] = {}

    class _FakeClient:
        async def embed(self, texts: list[str]):
            captured["texts"] = texts
            return [[0.1, 0.2], [0.3, 0.4]]

    monkeypatch.setattr(
        system_router,
        "get_embedding_config",
        lambda: SimpleNamespace(model="embed-test", binding="openai"),
    )
    monkeypatch.setattr(system_router, "get_embedding_client", lambda: _FakeClient())

    response = await system_router.test_embeddings_connection()

    assert response.success is True
    assert captured["texts"] == ["test", "retrieval batch probe"]


@pytest.mark.asyncio
async def test_embeddings_connection_rejects_partial_batch_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeClient:
        async def embed(self, texts: list[str]):
            return [[0.1, 0.2]]

    monkeypatch.setattr(
        system_router,
        "get_embedding_config",
        lambda: SimpleNamespace(model="embed-test", binding="openai"),
    )
    monkeypatch.setattr(system_router, "get_embedding_client", lambda: _FakeClient())

    response = await system_router.test_embeddings_connection()

    assert response.success is False
    assert response.message == "Embeddings connection failed: Invalid response"


@pytest.mark.asyncio
async def test_memory_usage_is_withheld_from_non_admins(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same reason /status strips model names: it is operational detail."""
    monkeypatch.setattr(system_router, "get_current_user", lambda: SimpleNamespace(is_admin=False))
    monkeypatch.setattr(
        system_router.memory_probe,
        "capture",
        lambda: _snapshot(ProcessMemory(pid=1, label="backend", rss_bytes=100)),
    )

    payload = await system_router.get_memory_usage()

    assert payload == {"available": False}


@pytest.mark.asyncio
async def test_memory_usage_groups_processes_by_role(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(system_router, "get_current_user", lambda: SimpleNamespace(is_admin=True))
    monkeypatch.setattr(
        system_router.memory_probe,
        "capture",
        lambda: _snapshot(
            ProcessMemory(pid=1, label="backend", rss_bytes=800),
            ProcessMemory(pid=2, label="web", rss_bytes=500),
            ProcessMemory(pid=3, label="sandbox", rss_bytes=40),
            ProcessMemory(pid=4, label="sandbox", rss_bytes=30),
        ),
    )

    payload = await system_router.get_memory_usage()

    assert payload["available"] is True
    assert payload["total_rss_bytes"] == 1370
    assert payload["usage_ratio"] == 1370 / (16 * 1024**3)
    # Concurrent sandboxes collapse into one row rather than flooding the tooltip.
    assert payload["processes"] == [
        {"label": "backend", "count": 1, "rss_bytes": 800},
        {"label": "web", "count": 1, "rss_bytes": 500},
        {"label": "sandbox", "count": 2, "rss_bytes": 70},
    ]


@pytest.mark.asyncio
async def test_memory_usage_folds_the_long_tail_into_other(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    limit = system_router.memory_probe.MAX_REPORTED_PROCESSES
    roles = [
        ProcessMemory(pid=i, label=f"role-{i}", rss_bytes=(limit + 5 - i) * 10)
        for i in range(limit + 3)
    ]
    monkeypatch.setattr(system_router, "get_current_user", lambda: SimpleNamespace(is_admin=True))
    monkeypatch.setattr(system_router.memory_probe, "capture", lambda: _snapshot(*roles))

    payload = await system_router.get_memory_usage()

    assert len(payload["processes"]) == limit + 1
    tail = payload["processes"][-1]
    assert tail["label"] == "other"
    assert tail["count"] == 3
    # Folding must not lose bytes — the rows still add up to the reported total.
    assert sum(row["rss_bytes"] for row in payload["processes"]) == payload["total_rss_bytes"]


@pytest.mark.asyncio
async def test_memory_usage_unavailable_when_no_process_can_be_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(system_router, "get_current_user", lambda: SimpleNamespace(is_admin=True))
    monkeypatch.setattr(system_router.memory_probe, "capture", lambda: _snapshot())

    payload = await system_router.get_memory_usage()

    assert payload == {"available": False}
