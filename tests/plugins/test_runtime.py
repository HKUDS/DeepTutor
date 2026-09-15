"""Runtime gate and Tool/Capability worker contract tests."""

from __future__ import annotations

import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from deeptutor.core.capability_protocol import CapabilityManifest, TurnCapability
from deeptutor.core.context import UnifiedContext
from deeptutor.plugins.manifest import parse_manifest
from deeptutor.plugins.registry import PluginInstallation, PluginRegistry
import deeptutor.plugins.runtime as runtime
from deeptutor.plugins.runtime import (
    PluginRuntimeError,
    PluginWorkerCapability,
    PluginWorkerTool,
    entry_point_allowed,
)
from deeptutor.runtime.stream_bus import StreamBus


def _raw_manifest() -> dict:
    return {
        "schema_version": "deeptutor.plugin/v1",
        "id": "org.deeptutor.learning_echo",
        "name": "Learning Echo Example",
        "version": "1.0.0",
        "description_i18n": {"en": "Example"},
        "author": "DeepTutor",
        "license": "Apache-2.0",
        "homepage": "https://example.com",
        "source_url": "https://example.com/source",
        "compatibility": {
            "deeptutor": ">=1.6,<3",
            "api": {"tool": "1", "capability": "1", "http_route": "1"},
        },
        "permissions": {"network": []},
        "dependencies": [],
        "extensions": [
            {"type": "tool", "id": "learning_echo", "entry_point": "learning_echo.worker"},
            {
                "type": "capability",
                "id": "learning_echo_capability",
                "entry_point": "learning_echo.worker",
            },
            {
                "type": "http_route",
                "id": "learning_echo_http",
                "entry_point": "learning_echo.worker",
                "path": "/echo",
                "methods": ["POST"],
                "auth": "public",
            },
        ],
    }


def _installation(tmp_path: Path) -> PluginInstallation:
    venv_path = tmp_path / "venv"
    venv_path.mkdir(exist_ok=True)
    return PluginInstallation(
        version="1.0.0",
        artifact_path=tmp_path / "artifact.whl",
        artifact_sha256="0" * 64,
        venv_path=venv_path,
        python_path=Path(sys.executable),
        installed_at="2026-09-07T00:00:00+00:00",
    )


def _registry(tmp_path: Path) -> PluginRegistry:
    manifest = parse_manifest(_raw_manifest())
    registry = PluginRegistry(
        state_path=tmp_path / "plugins.json",
        installed_distributions=[],
        deeptutor_version="1.6.0",
    )
    installation = _installation(tmp_path)
    state = registry.state_snapshot()
    state["plugins"][manifest.id] = {
        "manifest": manifest.to_dict(),
        "installation": installation.to_dict(),
        "history": [],
    }
    registry.replace_state(state)
    return registry


def test_entry_point_gate_requires_exact_permission_approval(tmp_path) -> None:
    registry = _registry(tmp_path)

    assert not entry_point_allowed(
        registry, extension_type="tool", entry_point="learning_echo.worker"
    )
    registry.approve("org.deeptutor.learning_echo")
    assert entry_point_allowed(registry, extension_type="tool", entry_point="learning_echo.worker")
    registry.set_enabled("org.deeptutor.learning_echo", False)
    assert not entry_point_allowed(
        registry, extension_type="tool", entry_point="learning_echo.worker"
    )


@pytest.mark.asyncio
async def test_example_worker_tool_and_capability(tmp_path, monkeypatch) -> None:
    manifest = parse_manifest(_raw_manifest())
    installation = _installation(tmp_path)
    example_root = Path(__file__).parents[2] / "examples" / "plugins" / "learning_echo"
    monkeypatch.setattr(
        "deeptutor.plugins.runtime._clean_env",
        lambda: {
            **dict(os.environ),
            "PYTHONPATH": str(example_root),
        },
    )

    tool = PluginWorkerTool(
        manifest=manifest,
        installation=installation,
        extension_id="learning_echo",
    )
    result = await tool.execute(message="hello")
    assert result.content == "learning echo: hello"

    capability = PluginWorkerCapability(
        manifest=manifest,
        installation=installation,
        extension_id="learning_echo_capability",
    )
    bus = StreamBus()
    await capability.run(UnifiedContext(user_message="hello"), bus)
    await bus.close()
    events = [event async for event in bus.subscribe()]
    assert events[0].content == "learning capability echo: hello"


def test_example_worker_http_route(tmp_path, monkeypatch) -> None:
    manifest = parse_manifest(_raw_manifest())
    installation = _installation(tmp_path)
    example_root = Path(__file__).parents[2] / "examples" / "plugins" / "learning_echo"
    monkeypatch.setattr(
        "deeptutor.plugins.runtime._clean_env",
        lambda: {**dict(os.environ), "PYTHONPATH": str(example_root)},
    )

    route = runtime.PluginWorkerHttpRoute(
        manifest=manifest,
        installation=installation,
        extension_id="learning_echo_http",
    )
    response = route.handle(
        method="POST",
        path="/echo",
        query={"tags": ("math", "spaced-repetition")},
        body={"message": "hello"},
    )

    assert response.status == 200
    assert response.headers == {"Cache-Control": "no-store"}
    assert response.body == {
        "method": "POST",
        "path": "/echo",
        "message": "hello",
        "auth": "public",
    }


def test_http_worker_response_status_and_headers_are_whitelisted(tmp_path, monkeypatch) -> None:
    manifest = parse_manifest(_raw_manifest())
    installation = _installation(tmp_path)

    class FixedClient:
        def __init__(self, response: dict) -> None:
            self.response = response
            self.payload: dict | None = None

        def request(self, operation: str, payload: dict | None = None) -> dict:
            assert operation == "handle_http"
            assert payload is not None and payload["http"]["auth"] == "public"
            self.payload = payload
            return self.response

    valid = runtime.PluginWorkerHttpRoute(
        manifest=manifest,
        installation=installation,
        extension_id="learning_echo_http",
    )
    client = FixedClient({"http": {"status": 201, "headers": {"cache-control": "no-store"}}})
    monkeypatch.setattr(valid, "_client", client)
    assert valid.handle(method="POST", path="/echo", query={}).body is None
    assert client.payload == {
        "http": {
            "method": "POST",
            "path": "/echo",
            "query": {},
            "body": None,
            "auth": "public",
        }
    }

    invalid_cases = [
        {"http": {"status": 301}},
        {"http": {"status": 200, "headers": {"Set-Cookie": "session=secret"}}},
        {"http": {"status": 200, "headers": {"Cache-Control": "public"}}},
        {"http": {"status": 204, "body": {}}},
        {"http": None},
    ]
    for response in invalid_cases:
        rejected = runtime.PluginWorkerHttpRoute(
            manifest=manifest,
            installation=installation,
            extension_id="learning_echo_http",
        )
        monkeypatch.setattr(rejected, "_client", FixedClient(response))
        with pytest.raises(PluginRuntimeError, match="handle_http"):
            rejected.handle(method="POST", path="/echo", query={})


def test_worker_permission_declaration_cannot_exceed_manifest(tmp_path, monkeypatch) -> None:
    manifest = parse_manifest(_raw_manifest())
    client = runtime._WorkerClient(
        python_path=Path(sys.executable),
        venv_path=tmp_path / "venv",
        module="learning_echo.worker",
        permissions=dict(manifest.permissions.scopes),
    )

    with pytest.raises(PluginRuntimeError, match="unapproved network"):
        client.validate_permissions({"network": ["https://unapproved.example"]})


def test_worker_error_response_is_rejected(tmp_path, monkeypatch) -> None:
    client = runtime._WorkerClient(
        python_path=Path(sys.executable),
        venv_path=tmp_path / "venv",
        module="learning_echo.worker",
        permissions={},
    )
    monkeypatch.setattr(
        runtime.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0, stdout='{"error": "contract violation"}', stderr=""
        ),
    )

    with pytest.raises(PluginRuntimeError, match="contract violation"):
        client.request("describe_tool")


def test_one_failed_worker_does_not_block_other_managed_extensions(tmp_path, monkeypatch) -> None:
    registry = _registry(tmp_path)
    registry.approve("org.deeptutor.learning_echo")

    class _Capability(TurnCapability):
        manifest = CapabilityManifest(name="learning_echo_capability", description="Echo")

        async def run(self, context: UnifiedContext, stream) -> None:
            return None

    def broken_tool(**_kwargs):
        raise runtime.PluginRuntimeError("worker unavailable")

    monkeypatch.setattr(runtime, "PluginWorkerTool", broken_tool)
    monkeypatch.setattr(runtime, "PluginWorkerCapability", lambda **_kwargs: _Capability())

    workers = runtime.load_enabled_workers(registry)

    assert isinstance(workers[0], _Capability)
