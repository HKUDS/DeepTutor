"""HTTP and introspection contracts for managed plugin extensions."""

from __future__ import annotations

import base64
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import sys
from typing import Any
from urllib.parse import urljoin
import zipfile

import pytest

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient
except Exception:  # pragma: no cover
    FastAPI = None
    TestClient = None

from deeptutor.plugins.lifecycle import PluginLifecycleManager
from deeptutor.plugins.manifest import parse_manifest
from deeptutor.plugins.registry import PluginInstallation, PluginRegistry
from deeptutor.plugins.runtime import PluginHttpResponse

pytestmark = pytest.mark.skipif(
    FastAPI is None or TestClient is None, reason="fastapi not installed"
)


def _raw_manifest() -> dict[str, Any]:
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
            "api": {
                "http_route": "1",
                "frontend_page": "1",
                "persistence_schema": "1",
                "app_connector": "1",
            },
        },
        "permissions": {"network": []},
        "dependencies": [],
        "extensions": [
            {
                "type": "http_route",
                "id": "learning_echo_http",
                "entry_point": "learning_echo.worker",
                "path": "/echo",
                "methods": ["POST"],
                "auth": "public",
            },
            {
                "type": "frontend_page",
                "id": "echo_page",
                "path": "/echo",
                "auth": "authenticated",
            },
            {
                "type": "persistence_schema",
                "id": "echo_store",
                "schema": "schemas/echo.json",
                "operations": ["read"],
            },
            {
                "type": "app_connector",
                "id": "echo_connector",
                "operations": ["import-course"],
            },
        ],
    }


def _installation(tmp_path: Path) -> PluginInstallation:
    venv_path = tmp_path / "venv"
    venv_path.mkdir(exist_ok=True)
    return PluginInstallation(
        version="1.0.0",
        artifact_path=tmp_path / "learning_echo.whl",
        artifact_sha256="0" * 64,
        venv_path=venv_path,
        python_path=Path(sys.executable),
        installed_at="2026-09-08T00:00:00+00:00",
    )


def _registry(tmp_path: Path, *, external: bool = False) -> PluginRegistry:
    manifest = parse_manifest(_raw_manifest())
    registry = PluginRegistry(
        state_path=tmp_path / "plugins.json",
        installed_distributions=[],
        deeptutor_version="1.6.0",
    )
    state = registry.state_snapshot()
    state["plugins"][manifest.id] = {
        "manifest": manifest.to_dict(),
        "installation": None if external else _installation(tmp_path).to_dict(),
        "history": [],
    }
    registry.replace_state(state)
    return registry


def _frontend_registry(tmp_path: Path, *, legacy_installation: bool = False) -> PluginRegistry:
    raw = _raw_manifest()
    raw["permissions"]["ui"] = ["sandboxed-iframe"]
    raw["extensions"][1]["manifest"] = "frontend/page.json"
    package_path = tmp_path / "package"
    frontend_path = package_path / "frontend"
    frontend_path.mkdir(parents=True)
    (frontend_path / "page.json").write_text(
        json.dumps(
            {
                "schema_version": "deeptutor.plugin-frontend-page/v1",
                "entry": "frontend/index.html",
                "assets": ["frontend/app.js", "frontend/index.html"],
            }
        ),
        encoding="utf-8",
    )
    (frontend_path / "index.html").write_text(
        '<html><body>plugin page<script src="assets/frontend/app.js"></script></body></html>',
        encoding="utf-8",
    )
    (frontend_path / "app.js").write_text("console.log('ready')", encoding="utf-8")
    (package_path / "secret.txt").write_text("secret", encoding="utf-8")

    manifest = parse_manifest(raw)
    registry = PluginRegistry(
        state_path=tmp_path / "plugins.json",
        installed_distributions=[],
        deeptutor_version="1.6.0",
    )
    installation = _installation(tmp_path)
    if not legacy_installation:
        installation = PluginInstallation(
            **{**installation.to_dict(), "package_path": package_path}
        )
    state = registry.state_snapshot()
    state["plugins"][manifest.id] = {
        "manifest": manifest.to_dict(),
        "installation": installation.to_dict(),
        "history": [],
    }
    registry.replace_state(state)
    return registry


def _record_line(name: str, payload: bytes) -> str:
    digest = base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).rstrip(b"=")
    return f"{name},sha256={digest.decode('ascii')},{len(payload)}"


class _ScriptSourceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.sources: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script":
            self.sources.extend(value for key, value in attrs if key == "src" and value)


@pytest.fixture
def client() -> TestClient:
    from deeptutor.api.routers import plugins

    app = FastAPI()
    app.include_router(plugins.router, prefix="/api/plugins")
    return TestClient(app)


def _use_registry(monkeypatch: pytest.MonkeyPatch, registry: PluginRegistry) -> None:
    from deeptutor.api.routers import plugins

    monkeypatch.setattr(plugins, "_registry_factory", lambda: registry)


def test_introspection_lists_only_approved_enabled_managed_extensions(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = _registry(tmp_path)
    _use_registry(monkeypatch, registry)

    assert client.get("/api/plugins/extensions").json() == {"plugins": []}

    registry.approve("org.deeptutor.learning_echo")
    body = client.get("/api/plugins/extensions").json()

    assert [plugin["id"] for plugin in body["plugins"]] == ["org.deeptutor.learning_echo"]
    assert [extension["type"] for extension in body["plugins"][0]["extensions"]] == [
        "http_route",
        "frontend_page",
        "persistence_schema",
        "app_connector",
    ]

    registry.set_enabled("org.deeptutor.learning_echo", False)
    assert client.get("/api/plugins/extensions").json() == {"plugins": []}


def test_introspection_requires_authentication(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from deeptutor.api.routers import plugins

    _use_registry(monkeypatch, _registry(tmp_path))

    async def reject(*, authorization: str | None = None, dt_token: str | None = None) -> None:
        raise HTTPException(status_code=401, detail="Authentication required")

    monkeypatch.setattr(plugins, "require_auth", reject)
    assert client.get("/api/plugins/extensions").status_code == 401


def test_managed_frontend_page_serves_only_declared_assets(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = _frontend_registry(tmp_path)
    _use_registry(monkeypatch, registry)
    base = "/api/plugins/org.deeptutor.learning_echo/pages/echo_page/"

    assert client.get(base).status_code == 404

    registry.approve("org.deeptutor.learning_echo")
    redirect = client.get(base.rstrip("/"), follow_redirects=False)
    extensions = client.get("/api/plugins/extensions").json()["plugins"][0]["extensions"]
    page = client.get(base)
    parser = _ScriptSourceParser()
    parser.feed(page.text)
    assert parser.sources == ["assets/frontend/app.js"]
    asset = client.get(urljoin(str(page.url), parser.sources[0]))
    secret = client.get(f"{base}/assets/secret.txt")

    assert redirect.status_code == 307
    assert redirect.headers["location"] == base
    assert extensions[1]["entry_url"] == base
    assert page.status_code == 200
    assert "plugin page" in page.text
    assert page.headers["content-type"].startswith("text/html")
    assert "sandbox allow-scripts" in page.headers["content-security-policy"]
    assert page.headers["x-content-type-options"] == "nosniff"
    assert page.headers["cross-origin-resource-policy"] == "same-origin"
    assert asset.status_code == 200
    assert asset.text == "console.log('ready')"
    assert asset.headers["cross-origin-resource-policy"] == "cross-origin"
    assert secret.status_code == 404


def test_frontend_page_host_auth_and_legacy_installation_boundary(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from deeptutor.api.routers import plugins

    auth_registry = _frontend_registry(tmp_path / "auth")
    legacy_registry = _frontend_registry(tmp_path / "legacy", legacy_installation=True)
    auth_registry.approve("org.deeptutor.learning_echo")
    legacy_registry.approve("org.deeptutor.learning_echo")
    original_auth = plugins.require_auth
    _use_registry(monkeypatch, auth_registry)

    async def reject(*, authorization: str | None = None, dt_token: str | None = None) -> None:
        raise HTTPException(status_code=401, detail="Authentication required")

    monkeypatch.setattr(plugins, "require_auth", reject)
    assert client.get("/api/plugins/org.deeptutor.learning_echo/pages/echo_page").status_code == 401

    _use_registry(monkeypatch, legacy_registry)
    monkeypatch.setattr(plugins, "require_auth", original_auth)
    assert client.get("/api/plugins/org.deeptutor.learning_echo/pages/echo_page").status_code == 404


@pytest.mark.asyncio
async def test_host_auth_dependencies_receive_request_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from deeptutor.api.routers import plugins

    request = SimpleNamespace(
        headers={"Authorization": "Bearer host-token"},
        cookies={"dt_token": "host-cookie"},
    )
    captured: dict[str, str] = {}

    async def fake_require_auth(*, authorization: str | None, dt_token: str | None) -> str:
        captured["authorization"] = authorization or ""
        captured["dt_token"] = dt_token or ""
        return "payload"

    async def fake_require_admin(*, payload: str) -> str:
        captured["admin_payload"] = payload
        return "admin"

    monkeypatch.setattr(plugins, "require_auth", fake_require_auth)
    monkeypatch.setattr(plugins, "require_admin", fake_require_admin)

    await plugins._require_authenticated(request)
    await plugins._require_admin(request)

    assert captured == {
        "authorization": "Bearer host-token",
        "dt_token": "host-cookie",
        "admin_payload": "payload",
    }


def test_managed_route_requires_approval_and_enablement(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = _registry(tmp_path)
    _use_registry(monkeypatch, registry)

    assert client.post("/api/plugins/org.deeptutor.learning_echo/echo").status_code == 404

    registry.approve("org.deeptutor.learning_echo")
    assert client.post("/api/plugins/org.deeptutor.learning_echo/echo").status_code == 500

    registry.set_enabled("org.deeptutor.learning_echo", False)
    assert client.post("/api/plugins/org.deeptutor.learning_echo/echo").status_code == 404


def test_external_distributions_cannot_expose_managed_http_routes(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = _registry(tmp_path, external=True)
    registry.approve("org.deeptutor.learning_echo")
    _use_registry(monkeypatch, registry)

    assert client.get("/api/plugins/extensions").json() == {"plugins": []}
    assert client.post("/api/plugins/org.deeptutor.learning_echo/echo").status_code == 404


def test_http_route_auth_is_enforced_by_host_without_forwarding_credentials(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from deeptutor.api.routers import plugins

    registry = _registry(tmp_path)
    registry.approve("org.deeptutor.learning_echo")
    _use_registry(monkeypatch, registry)
    captured: dict[str, Any] = {}

    class StubRoute:
        def __init__(self, **kwargs: Any) -> None:
            self.extension = kwargs["manifest"].extensions[0]

        def handle(self, **kwargs: Any) -> PluginHttpResponse:
            captured.update(kwargs)
            return PluginHttpResponse(status=200, body={"ok": True})

    monkeypatch.setattr(plugins, "PluginWorkerHttpRoute", StubRoute)
    headers = {"Authorization": "Bearer secret", "Cookie": "session=secret"}

    public = client.post(
        "/api/plugins/org.deeptutor.learning_echo/echo",
        json={"message": "hello"},
        headers=headers,
    )
    assert public.status_code == 200
    assert captured == {
        "method": "POST",
        "path": "/echo",
        "query": {},
        "body": {"message": "hello"},
    }

    async def reject_auth(*, authorization: str | None = None, dt_token: str | None = None) -> None:
        raise HTTPException(status_code=401, detail="Authentication required")

    async def allow_auth(*, authorization: str | None = None, dt_token: str | None = None) -> str:
        return "payload"

    async def reject_admin(*, payload: object = None) -> None:
        raise HTTPException(status_code=403, detail="Admin access required")

    state = registry.state_snapshot()
    manifest = parse_manifest(state["plugins"]["org.deeptutor.learning_echo"]["manifest"])
    for policy, reject in (("authenticated", reject_auth), ("admin", reject_admin)):
        extension = manifest.extensions[0]
        object.__setattr__(extension, "auth", policy)
        state["plugins"]["org.deeptutor.learning_echo"]["manifest"] = manifest.to_dict()
        registry.replace_state(state)
        monkeypatch.setattr(
            plugins,
            "require_auth",
            reject_auth if policy == "authenticated" else allow_auth,
        )
        monkeypatch.setattr(plugins, "require_admin", reject_admin)
        response = client.post(
            "/api/plugins/org.deeptutor.learning_echo/echo",
            json={},
            headers=headers,
        )
        assert response.status_code == (401 if policy == "authenticated" else 403)


def test_http_route_rejects_disallowed_method_and_malformed_json(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = _registry(tmp_path)
    registry.approve("org.deeptutor.learning_echo")
    _use_registry(monkeypatch, registry)

    assert client.get("/api/plugins/org.deeptutor.learning_echo/echo").status_code == 405
    assert (
        client.post(
            "/api/plugins/org.deeptutor.learning_echo/echo",
            content=b"{invalid",
            headers={"Content-Type": "application/json"},
        ).status_code
        == 400
    )


def test_real_wheel_http_flow_uses_managed_worker_subprocess(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = _raw_manifest()
    raw["permissions"]["ui"] = ["sandboxed-iframe"]
    raw["extensions"][1]["manifest"] = "frontend/page.json"
    wheel_path = tmp_path / "learning_echo-1.0.0-py3-none-any.whl"
    source_root = Path(__file__).parents[2] / "examples" / "plugins" / "learning_echo"
    files = {
        "learning_echo/deeptutor.plugin.json": json.dumps(raw).encode("utf-8"),
        "learning_echo/__init__.py": (
            '"""Minimal dependency-free DeepTutor plugin worker."""\n'
        ).encode("utf-8"),
        "learning_echo/worker.py": (source_root / "learning_echo" / "worker.py").read_bytes(),
        "learning_echo/frontend/page.json": (
            source_root / "learning_echo" / "frontend" / "page.json"
        ).read_bytes(),
        "learning_echo/frontend/index.html": (
            source_root / "learning_echo" / "frontend" / "index.html"
        ).read_bytes(),
        "learning_echo/frontend/app.js": (
            source_root / "learning_echo" / "frontend" / "app.js"
        ).read_bytes(),
        "learning_echo-1.0.0.dist-info/METADATA": ("Name: learning-echo\nVersion: 1.0.0\n").encode(
            "utf-8"
        ),
        "learning_echo-1.0.0.dist-info/WHEEL": (
            "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
        ).encode("utf-8"),
    }
    with zipfile.ZipFile(wheel_path, "w") as archive:
        for name, payload in files.items():
            archive.writestr(name, payload)
        record_name = "learning_echo-1.0.0.dist-info/RECORD"
        archive.writestr(
            record_name,
            "\n".join([_record_line(name, payload) for name, payload in files.items()])
            + f"\n{record_name},,\n",
        )

    registry = PluginRegistry(
        state_path=tmp_path / "plugins.json",
        installed_distributions=[],
        deeptutor_version="1.6.0",
    )
    manager = PluginLifecycleManager(registry, root=tmp_path / "plugin-root")
    manager.install(wheel_path)
    registry.approve("org.deeptutor.learning_echo")
    _use_registry(monkeypatch, registry)
    record = registry.get_plugin("org.deeptutor.learning_echo")
    assert record is not None and record.installation is not None

    response = client.post(
        "/api/plugins/org.deeptutor.learning_echo/echo?tag=math",
        json={"message": "hello"},
        headers={"Authorization": "Bearer must-not-forward", "Cookie": "session=secret"},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "method": "POST",
        "path": "/echo",
        "message": "hello",
        "auth": "public",
    }

    page = client.get("/api/plugins/org.deeptutor.learning_echo/pages/echo_page")
    parser = _ScriptSourceParser()
    parser.feed(page.text)
    assert parser.sources == ["assets/frontend/app.js"]
    asset = client.get(urljoin(str(page.url), parser.sources[0]))

    assert page.status_code == 200
    assert "Learning Echo" in page.text
    assert "sandbox allow-scripts" in page.headers["content-security-policy"]
    assert asset.status_code == 200
    assert "restricted asset context" in asset.text
