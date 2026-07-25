from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import system as system_router
from deeptutor.update import Installation, InstallMode, UpdateCheck, UpdateStatus
from deeptutor.update.jobs import JobStatus, UpdateJobStore
from deeptutor.update.source import SourceUpdateError


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
async def test_update_endpoint_returns_the_coordinator_result() -> None:
    class AvailableUpdate:
        def check(self) -> UpdateCheck:
            return UpdateCheck(
                status=UpdateStatus.AVAILABLE,
                current_version="1.5.4",
                latest_version="1.6.0",
                install_mode=InstallMode.PYPI,
                can_auto_update=True,
                release_url=("https://github.com/HKUDS/DeepTutor/releases/tag/v1.6.0"),
                detail="installed distribution",
            )

    response = await system_router.get_update_status(AvailableUpdate())

    assert response.model_dump(mode="json") == {
        "status": "available",
        "current_version": "1.5.4",
        "latest_version": "1.6.0",
        "install_mode": "pypi",
        "can_auto_update": True,
        "release_url": "https://github.com/HKUDS/DeepTutor/releases/tag/v1.6.0",
        "detail": "installed distribution",
    }


def test_update_endpoint_is_available_through_the_system_http_route() -> None:
    class UpToDate:
        def check(self) -> UpdateCheck:
            return UpdateCheck(
                status=UpdateStatus.UP_TO_DATE,
                current_version="1.5.4",
                latest_version="1.5.4",
                install_mode=InstallMode.SOURCE_WEB,
                can_auto_update=True,
                release_url=("https://github.com/HKUDS/DeepTutor/releases/tag/v1.5.4"),
                detail="editable full installation",
            )

    app = FastAPI()
    app.include_router(system_router.router, prefix="/api/v1/system")
    app.dependency_overrides[system_router.get_update_coordinator] = UpToDate

    response = TestClient(app).get("/api/v1/system/update")

    assert response.status_code == 200
    assert response.json()["status"] == "up_to_date"
    assert response.json()["install_mode"] == "source_web"


class _AvailablePypiUpdate:
    def check(self) -> UpdateCheck:
        return UpdateCheck(
            status=UpdateStatus.AVAILABLE,
            current_version="1.5.4",
            latest_version="1.6.0",
            install_mode=InstallMode.PYPI,
            can_auto_update=True,
            release_url="https://github.com/HKUDS/DeepTutor/releases/tag/v1.6.0",
            detail="installed distribution",
        )


class _IdleConversations:
    async def has_live_executions(self) -> bool:
        return False


def _pypi_installation() -> Installation:
    return Installation(
        mode=InstallMode.PYPI,
        current_version="1.5.4",
        package_name="deeptutor",
    )


class _NoSourcePreflight:
    def preflight(self, installation, target_version):
        raise AssertionError("PyPI updates must not run source preflight")


@pytest.mark.asyncio
async def test_web_update_refuses_to_interrupt_a_live_conversation(tmp_path: Path) -> None:
    class BusyConversations:
        async def has_live_executions(self) -> bool:
            return True

    with pytest.raises(HTTPException) as exc_info:
        await system_router.request_web_update(
            system_router.WebUpdateRequest(confirmation="update-and-restart"),
            coordinator=_AvailablePypiUpdate(),
            conversations=BusyConversations(),
            store=UpdateJobStore(tmp_path),
            launcher_ready=True,
            installation=_pypi_installation(),
            source_preflight=_NoSourcePreflight(),
        )

    assert exc_info.value.status_code == 409
    assert "conversation" in str(exc_info.value.detail).lower()
    assert not (tmp_path / "state.json").exists()


@pytest.mark.asyncio
async def test_web_update_persists_a_restart_request(tmp_path: Path) -> None:
    store = UpdateJobStore(tmp_path)

    response = await system_router.request_web_update(
        system_router.WebUpdateRequest(confirmation="update-and-restart"),
        coordinator=_AvailablePypiUpdate(),
        conversations=_IdleConversations(),
        store=store,
        launcher_ready=True,
        installation=_pypi_installation(),
        source_preflight=_NoSourcePreflight(),
    )

    assert response.status is JobStatus.PENDING
    assert response.target_version == "1.6.0"
    assert store.load().restart_requested is True


@pytest.mark.asyncio
async def test_source_web_update_preflights_and_persists_the_checkout(
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "checkout"
    installation = Installation(
        mode=InstallMode.SOURCE_WEB,
        current_version="1.5.4",
        package_name="deeptutor",
        source_root=checkout,
    )

    class AvailableSourceUpdate:
        def check(self) -> UpdateCheck:
            return UpdateCheck(
                status=UpdateStatus.AVAILABLE,
                current_version="1.5.4",
                latest_version="1.6.0",
                install_mode=InstallMode.SOURCE_WEB,
                can_auto_update=True,
                release_url="https://github.com/HKUDS/DeepTutor/releases/tag/v1.6.0",
                detail="editable full installation",
            )

    seen: list[tuple[Installation, str]] = []

    class SourcePreflight:
        def preflight(self, detected, target_version):
            seen.append((detected, target_version))

    store = UpdateJobStore(tmp_path / "jobs")
    response = await system_router.request_web_update(
        system_router.WebUpdateRequest(confirmation="update-and-restart"),
        coordinator=AvailableSourceUpdate(),
        conversations=_IdleConversations(),
        store=store,
        launcher_ready=True,
        installation=installation,
        source_preflight=SourcePreflight(),
    )

    assert response.status is JobStatus.PENDING
    assert seen == [(installation, "1.6.0")]
    assert store.load().kind == "source"
    assert store.load().source_root == str(checkout.resolve())


@pytest.mark.asyncio
async def test_source_web_update_refuses_a_failed_preflight(tmp_path: Path) -> None:
    installation = Installation(
        mode=InstallMode.SOURCE_WEB,
        current_version="1.5.4",
        package_name="deeptutor",
        source_root=tmp_path / "checkout",
    )

    class AvailableSourceUpdate:
        def check(self) -> UpdateCheck:
            return UpdateCheck(
                status=UpdateStatus.AVAILABLE,
                current_version="1.5.4",
                latest_version="1.6.0",
                install_mode=InstallMode.SOURCE_WEB,
                can_auto_update=True,
                release_url=None,
                detail="editable full installation",
            )

    class BrokenPreflight:
        def preflight(self, detected, target_version):
            raise SourceUpdateError("working tree is not clean")

    store = UpdateJobStore(tmp_path / "jobs")
    with pytest.raises(HTTPException) as exc_info:
        await system_router.request_web_update(
            system_router.WebUpdateRequest(confirmation="update-and-restart"),
            coordinator=AvailableSourceUpdate(),
            conversations=_IdleConversations(),
            store=store,
            launcher_ready=True,
            installation=installation,
            source_preflight=BrokenPreflight(),
        )

    assert exc_info.value.status_code == 409
    assert "working tree is not clean" in str(exc_info.value.detail)
    assert not store.state_path.exists()


def test_web_update_http_route_is_admin_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deeptutor.api.routers import auth as auth_router

    app = FastAPI()
    app.include_router(system_router.router, prefix="/api/v1/system")
    app.dependency_overrides[system_router.get_update_coordinator] = _AvailablePypiUpdate
    app.dependency_overrides[system_router.get_conversation_activity] = _IdleConversations
    app.dependency_overrides[system_router.get_update_job_store] = lambda: UpdateJobStore(tmp_path)
    app.dependency_overrides[system_router.is_launcher_available] = lambda: True
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)

    response = TestClient(app).post(
        "/api/v1/system/update",
        json={"confirmation": "update-and-restart"},
    )

    assert response.status_code == 401


def test_web_update_http_route_requires_confirmation_and_creates_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deeptutor.api.routers import auth as auth_router

    app = FastAPI()
    app.include_router(system_router.router, prefix="/api/v1/system")
    app.dependency_overrides[system_router.get_update_coordinator] = _AvailablePypiUpdate
    app.dependency_overrides[system_router.get_conversation_activity] = _IdleConversations
    app.dependency_overrides[system_router.get_update_job_store] = lambda: UpdateJobStore(tmp_path)
    app.dependency_overrides[system_router.is_launcher_available] = lambda: True
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", False)
    client = TestClient(app)

    rejected = client.post(
        "/api/v1/system/update",
        json={"confirmation": "yes"},
    )
    accepted = client.post(
        "/api/v1/system/update",
        json={"confirmation": "update-and-restart"},
    )

    assert rejected.status_code == 422
    assert accepted.status_code == 202
    assert accepted.json()["status"] == "pending"
    assert UpdateJobStore(tmp_path).load().restart_requested is True


def test_source_web_update_is_available_through_the_http_route(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deeptutor.api.routers import auth as auth_router

    checkout = tmp_path / "checkout"
    installation = Installation(
        mode=InstallMode.SOURCE_WEB,
        current_version="1.5.4",
        package_name="deeptutor",
        source_root=checkout,
    )

    class AvailableSourceUpdate:
        def check(self) -> UpdateCheck:
            return UpdateCheck(
                status=UpdateStatus.AVAILABLE,
                current_version="1.5.4",
                latest_version="1.6.0",
                install_mode=InstallMode.SOURCE_WEB,
                can_auto_update=True,
                release_url=None,
                detail="editable full installation",
            )

    class SourcePreflight:
        def preflight(self, detected, target_version):
            return None

    store = UpdateJobStore(tmp_path / "jobs")
    app = FastAPI()
    app.include_router(system_router.router, prefix="/api/v1/system")
    app.dependency_overrides[system_router.get_update_coordinator] = AvailableSourceUpdate
    app.dependency_overrides[system_router.get_conversation_activity] = _IdleConversations
    app.dependency_overrides[system_router.get_update_job_store] = lambda: store
    app.dependency_overrides[system_router.is_launcher_available] = lambda: True
    app.dependency_overrides[system_router.get_current_installation] = lambda: installation
    app.dependency_overrides[system_router.get_source_preflight] = SourcePreflight
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", False)

    response = TestClient(app).post(
        "/api/v1/system/update",
        json={"confirmation": "update-and-restart"},
    )

    assert response.status_code == 202
    assert store.load().kind == "source"
    assert store.load().source_root == str(checkout.resolve())


def test_update_job_status_survives_a_router_recreation(tmp_path: Path) -> None:
    store = UpdateJobStore(tmp_path)
    job = store.create_pypi(
        current_version="1.5.4",
        target_version="1.6.0",
        restart_requested=True,
    )
    store.prepare_restart(job.id, home=tmp_path / "home")
    store.mark_running(job.id)
    store.mark_restarting(job.id)

    response = system_router.get_update_job(store)

    assert response is not None
    assert response.id == job.id
    assert response.status is JobStatus.RESTARTING
    assert response.restart_count == 1
