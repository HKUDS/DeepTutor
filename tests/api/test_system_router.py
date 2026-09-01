from __future__ import annotations

from types import SimpleNamespace

import pytest

from deeptutor.api.routers import system as system_router
from deeptutor.runtime.memory_probe import MemorySnapshot, ProcessMemory
from deeptutor.services.app_update import (
    Installation,
    ReleaseInfo,
    UpdateJobStore,
    VersionCheckResult,
)


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


class _UpdateSettings:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled

    def load_system(self, *, include_process_overrides: bool = True) -> dict[str, object]:
        del include_process_overrides
        return {"version_check_enabled": self.enabled}

    def save_system(self, payload: dict[str, object]) -> dict[str, object]:
        self.enabled = bool(payload["version_check_enabled"])
        return payload


class _VersionService:
    def __init__(self, result: VersionCheckResult) -> None:
        self.result = result
        self.forces: list[bool] = []

    async def check(self, *, force: bool = False) -> VersionCheckResult:
        self.forces.append(force)
        return self.result

    def cached(self) -> VersionCheckResult:
        return self.result


def _update_result() -> VersionCheckResult:
    return VersionCheckResult(
        current_version="1.6.1",
        release=ReleaseInfo(
            version="1.7.0",
            name="DeepTutor 1.7",
            published_at="2026-08-30T00:00:00Z",
            url="https://github.com/HKUDS/DeepTutor/releases/tag/v1.7.0",
            excerpt="A stable release.",
            migration_warning=False,
        ),
        checked_at="2026-08-30T00:00:00+00:00",
        cached=False,
    )


def _pypi_installation() -> Installation:
    return Installation(
        mode="pypi",
        current_version="1.6.1",
        automatic_update=True,
        command="pip install -U deeptutor",
        reason="",
    )


@pytest.mark.asyncio
async def test_update_status_combines_cached_release_and_installation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    version_service = _VersionService(_update_result())
    monkeypatch.setattr(system_router, "get_runtime_settings_service", _UpdateSettings)
    monkeypatch.setattr(system_router, "get_version_check_service", lambda: version_service)
    monkeypatch.setattr(system_router, "get_update_installation", _pypi_installation)
    monkeypatch.setattr(system_router, "launcher_available", lambda: True)
    monkeypatch.setattr(
        system_router,
        "get_update_job_store",
        lambda: UpdateJobStore(tmp_path / "update"),
    )
    monkeypatch.setattr(
        system_router,
        "get_current_user",
        lambda: SimpleNamespace(is_admin=True),
    )

    payload = await system_router.get_update_status()

    assert payload["current_version"] == "1.6.1"
    assert payload["release"]["version"] == "1.7.0"
    assert payload["update_available"] is True
    assert payload["installation"]["mode"] == "pypi"
    assert version_service.forces == [False]


@pytest.mark.asyncio
async def test_managed_update_refuses_live_conversation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Activity:
        async def reserve_managed_update(self, _reserve):
            return None

    monkeypatch.setattr(system_router, "get_runtime_settings_service", _UpdateSettings)
    monkeypatch.setattr(system_router, "launcher_available", lambda: True)
    monkeypatch.setattr(system_router, "get_turn_activity", _Activity)

    with pytest.raises(Exception) as raised:
        await system_router.request_managed_update(
            system_router.ManagedUpdateRequest(confirmation="update-and-restart")
        )

    assert getattr(raised.value, "status_code", None) == 409


@pytest.mark.asyncio
async def test_managed_update_creates_durable_job(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    class _Activity:
        async def reserve_managed_update(self, reserve):
            return reserve()

    store = UpdateJobStore(tmp_path / "update")
    monkeypatch.setattr(system_router, "get_runtime_settings_service", _UpdateSettings)
    monkeypatch.setattr(system_router, "launcher_available", lambda: True)
    monkeypatch.setattr(system_router, "get_turn_activity", _Activity)
    monkeypatch.setattr(system_router, "get_update_installation", _pypi_installation)
    monkeypatch.setattr(
        system_router, "get_version_check_service", lambda: _VersionService(_update_result())
    )
    monkeypatch.setattr(system_router, "get_update_job_store", lambda: store)

    payload = await system_router.request_managed_update(
        system_router.ManagedUpdateRequest(confirmation="update-and-restart")
    )

    assert payload["status"] == "pending"
    assert payload["target_version"] == "1.7.0"
    assert store.load().id == payload["id"]


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
