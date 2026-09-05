from __future__ import annotations

import asyncio
from pathlib import Path
import threading
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import reading_extensions
from deeptutor.reading import ReadingStore
from deeptutor.reading.extensions import (
    ReadingAction,
    ReadingExtensionManifest,
    ReadingExtensionRegistry,
    ReadingExtensionResult,
)
from deeptutor.reading.models import ReadingPosition
from deeptutor.services.path_service import PathService


@pytest.fixture
def material(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path))
    PathService.reset_instance()
    source = tmp_path / "source.txt"
    source.write_text("Visible passage with a verified phrase.", encoding="utf-8")
    manifest = ReadingStore().ingest(source)
    yield manifest
    PathService.reset_instance()


def _client(monkeypatch, extension) -> TestClient:
    registry = ReadingExtensionRegistry([extension])
    monkeypatch.setattr(
        reading_extensions,
        "get_reading_extension_registry",
        lambda: registry,
    )
    app = FastAPI()
    app.include_router(reading_extensions.router, prefix="/api/reading")
    return TestClient(app)


def _extension(run_action, *, requires=(), result_types=("card",)):
    return SimpleNamespace(
        manifest=ReadingExtensionManifest(
            id="sample",
            version="1.0.0",
            name="Sample",
            actions=[
                ReadingAction(
                    id="open",
                    label="Open",
                    requires=list(requires),
                )
            ],
            result_types=list(result_types),
        ),
        run_action=run_action,
    )


def test_action_receives_only_server_verified_visible_text(material, monkeypatch):
    captured = {}

    def run(_action, context):
        captured.update(context.model_dump())
        return ReadingExtensionResult(type="card", payload={"body": "ok"})

    client = _client(monkeypatch, _extension(run))
    response = client.post(
        f"/api/reading/materials/{material.material_id}/extensions/sample/actions/open",
        json={"locator": 1, "selection": "forged text", "locale": "en"},
    )
    assert response.status_code == 200, response.text
    assert captured["selection"] == ""
    assert captured["visible_text"] == "Visible passage with a verified phrase."


def test_source_anchor_is_loaded_from_server_position(material, monkeypatch):
    ReadingStore().save_position(
        material.material_id,
        ReadingPosition(locator=1, source_anchor="server-anchor"),
    )
    captured = {}

    def run(_action, context):
        captured.update(context.model_dump())
        return ReadingExtensionResult(type="card")

    client = _client(monkeypatch, _extension(run))
    response = client.post(
        f"/api/reading/materials/{material.material_id}/extensions/sample/actions/open",
        json={"locator": 1, "source_anchor": "forged-anchor"},
    )

    assert response.status_code == 200, response.text
    assert captured["source_anchor"] == "server-anchor"


def test_selection_requirement_rejects_unverified_text(material, monkeypatch):
    client = _client(
        monkeypatch,
        _extension(lambda *_: pytest.fail("must not run"), requires=("selection",)),
    )
    response = client.post(
        f"/api/reading/materials/{material.material_id}/extensions/sample/actions/open",
        json={"locator": 1, "selection": "not in the material"},
    )
    assert response.status_code == 400


def test_oversized_unit_returns_protocol_error(material, monkeypatch):
    unit_path = ReadingStore().root / material.material_id / "units" / "0001.txt"
    unit_path.write_text("x" * 60_001, encoding="utf-8")
    client = _client(
        monkeypatch,
        _extension(lambda *_: pytest.fail("must not run")),
    )

    response = client.post(
        f"/api/reading/materials/{material.material_id}/extensions/sample/actions/open",
        json={"locator": 1},
    )

    assert response.status_code == 422
    assert "too large" in response.json()["detail"]


@pytest.mark.parametrize(
    "run_action",
    [
        lambda *_: (_ for _ in ()).throw(RuntimeError("broken plugin")),
        lambda *_: ReadingExtensionResult(type="feedback"),
    ],
)
def test_extension_failures_are_isolated(material, monkeypatch, run_action):
    client = _client(monkeypatch, _extension(run_action))
    response = client.post(
        f"/api/reading/materials/{material.material_id}/extensions/sample/actions/open",
        json={"locator": 1},
    )
    assert response.status_code == 503
    assert response.json()["detail"]["recoverable"] is True


def test_hanging_extension_action_times_out(material, monkeypatch):
    async def run(*_args):
        await asyncio.sleep(1)

    monkeypatch.setattr(reading_extensions, "ACTION_TIMEOUT_S", 0.01)
    client = _client(monkeypatch, _extension(run))

    response = client.post(
        f"/api/reading/materials/{material.material_id}/extensions/sample/actions/open",
        json={"locator": 1},
    )

    assert response.status_code == 503
    assert response.json()["detail"]["recoverable"] is True


def test_timed_out_sync_extension_opens_circuit_without_queueing(material, monkeypatch):
    release = threading.Event()
    calls = 0

    def run(*_args):
        nonlocal calls
        calls += 1
        release.wait(timeout=1)
        return ReadingExtensionResult(type="card")

    monkeypatch.setattr(reading_extensions, "ACTION_TIMEOUT_S", 0.01)
    client = _client(monkeypatch, _extension(run))

    try:
        first = client.post(
            f"/api/reading/materials/{material.material_id}/extensions/sample/actions/open",
            json={"locator": 1},
        )
        second = client.post(
            f"/api/reading/materials/{material.material_id}/extensions/sample/actions/open",
            json={"locator": 1},
        )

        assert first.status_code == 503
        assert second.status_code == 503
        assert calls == 1
    finally:
        release.set()


def test_async_timeout_allows_retry(material, monkeypatch):
    calls = 0

    async def run(*args):
        nonlocal calls
        calls += 1
        if calls == 1:
            await asyncio.sleep(1)
        return ReadingExtensionResult(type="card", message="retried")

    monkeypatch.setattr(reading_extensions, "ACTION_TIMEOUT_S", 0.01)
    client = _client(monkeypatch, _extension(run))
    url = f"/api/reading/materials/{material.material_id}/extensions/sample/actions/open"
    assert client.post(url, json={"locator": 1}).json()["detail"]["code"] == "timeout"
    assert client.post(url, json={"locator": 1}).status_code == 200


def test_llm_selection_is_scoped_and_reset(material, monkeypatch):
    from deeptutor.multi_user import model_access
    from deeptutor.services.llm import config as configs
    from deeptutor.services.model_selection import runtime

    seen = []
    monkeypatch.setattr(model_access, "apply_allowed_llm_selection", lambda selection: selection)
    monkeypatch.setattr(
        runtime,
        "resolve_llm_config_for_selection",
        lambda selection: configs.LLMConfig(model=selection["model_id"], api_key="test"),
    )

    def run(*args):
        seen.append(configs.get_llm_config().model)
        return ReadingExtensionResult(type="card")

    extension = _extension(run)
    extension.manifest.requires_llm = True
    client = _client(monkeypatch, extension)
    url = f"/api/reading/materials/{material.material_id}/extensions/sample/actions/open"
    for model in ["chosen-a", "chosen-b"]:
        assert (
            client.post(
                url,
                json={"locator": 1, "llm_selection": {"profile_id": "granted", "model_id": model}},
            ).status_code
            == 200
        )
    assert seen == ["chosen-a", "chosen-b"]
    assert configs._SCOPED_LLM_CONFIG.get() is None


def test_model_errors_are_actionable_and_offline_does_not_resolve(material, monkeypatch):
    from deeptutor.multi_user import model_access
    from deeptutor.services.model_selection import runtime

    def missing(_):
        raise ValueError("private model configuration details")

    monkeypatch.setattr(runtime, "activate_llm_selection", missing)
    extension = _extension(lambda *_: ReadingExtensionResult(type="card"))
    client = _client(monkeypatch, extension)
    url = f"/api/reading/materials/{material.material_id}/extensions/sample/actions/open"
    assert client.post(url, json={"locator": 1}).status_code == 200
    extension.manifest.requires_llm = True
    response = client.post(url, json={"locator": 1})
    assert response.json()["detail"]["code"] == "model_not_configured"
    assert "private" not in response.text

    def denied(_):
        raise PermissionError("private grant information")

    monkeypatch.setattr(model_access, "apply_allowed_llm_selection", denied)
    response = client.post(
        url, json={"locator": 1, "llm_selection": {"profile_id": "denied", "model_id": "denied"}}
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "model_forbidden"


def test_learner_model_grants_with_empty_shared_default(material, monkeypatch):
    from deeptutor.multi_user import context as user_context
    from deeptutor.multi_user import model_access
    from deeptutor.services.config import model_catalog
    from deeptutor.services.llm import config as configs
    from deeptutor.services.model_selection import runtime

    learner = SimpleNamespace(id="learner", is_admin=False)
    monkeypatch.setattr(model_access, "get_current_user", lambda: learner)
    monkeypatch.setattr(user_context, "get_current_user", lambda: learner)
    monkeypatch.setattr(
        model_access,
        "redacted_model_access",
        lambda _: {"llm": [{"profile_id": "granted", "model_id": "chosen", "available": True}]},
    )
    monkeypatch.setattr(
        model_catalog,
        "get_model_catalog_service",
        lambda: SimpleNamespace(load=lambda: {"services": {"llm": {}}}),
    )
    monkeypatch.setattr(
        runtime,
        "resolve_llm_config_for_selection",
        lambda selection: configs.LLMConfig(model=selection["model_id"], api_key="test"),
    )
    seen = []

    async def run(*args):
        seen.append(configs.get_llm_config().model)
        return ReadingExtensionResult(type="card")

    extension = _extension(run)
    extension.manifest.requires_llm = True
    client = _client(monkeypatch, extension)
    # Material/extension authorization is covered separately; retain the real model validator.
    monkeypatch.setattr(reading_extensions, "assert_learning_material", lambda _: None)
    monkeypatch.setattr(reading_extensions, "allowed_reading_extensions", lambda: None)
    url = f"/api/reading/materials/{material.material_id}/extensions/sample/actions/open"
    assert client.post(url, json={"locator": 1}).json()["detail"]["code"] == "model_not_configured"
    for model, status in [("chosen", 200), ("other", 403)]:
        response = client.post(
            url, json={"locator": 1, "llm_selection": {"profile_id": "granted", "model_id": model}}
        )
        assert response.status_code == status, response.text
    assert seen == ["chosen"]
