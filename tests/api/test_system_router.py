from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import system as system_router
from deeptutor.update import InstallMode, UpdateCheck, UpdateStatus


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
