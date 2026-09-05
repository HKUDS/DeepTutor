from __future__ import annotations

import io
from types import SimpleNamespace
import zipfile

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import auth, reading_plugins
from deeptutor.reading import plugin_manager as manager


def wheel(version="0.1.0", requirement="deeptutor>=1.6.4,<2", extra=None):
    buffer = io.BytesIO()
    folder = f"{manager.NAMESPACE}-{version}.dist-info"
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            folder + "/METADATA",
            f"Name: {manager.PACKAGE}\nVersion: {version}\nRequires-Python: >=3.11\nRequires-Dist: {requirement}\n",
        )
        archive.writestr(
            folder + "/WHEEL", "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
        )
        archive.writestr(
            folder + "/entry_points.txt",
            "[deeptutor.reading_extensions]\n"
            + "\n".join(f"{key} = {value}" for key, value in manager.EXTENSIONS.items()),
        )
        for target in manager.EXTENSIONS.values():
            archive.writestr(
                target.split(":")[0].replace(".", "/") + ".py",
                "raise RuntimeError('must not execute during install')",
            )
        if extra:
            archive.writestr(*extra)
    return buffer.getvalue()


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(manager, "root", lambda: tmp_path / "plugins")
    monkeypatch.setattr(manager, "ACTIVE_STATE", dict(manager.DEFAULT))


def test_install_update_and_uninstall_require_restart(monkeypatch):
    initial = manager.status()
    assert not initial["restart_required"]
    installed = manager.install(wheel())
    assert installed["desired"]["version"] == "0.1.0"
    assert installed["active"]["mode"] == "builtin"
    assert installed["restart_required"]
    # A newly started worker uses the persisted generation.
    monkeypatch.setattr(manager, "ACTIVE_STATE", manager.read_state())
    assert not manager.status()["restart_required"]
    manager.configure(extension="vocabulary", enabled=False)
    updated = manager.install(wheel("0.2.0"))
    assert updated["desired"]["disabled"] == ["vocabulary"]
    assert updated["active"]["version"] == "0.1.0"
    removed = manager.configure(mode="disabled")
    assert removed["restart_required"]
    monkeypatch.setattr(manager, "ACTIVE_STATE", manager.read_state())
    assert manager.load_overrides() == ({}, set(manager.EXTENSIONS))
    restored = manager.configure(mode="builtin")
    assert restored["desired"] == manager.DEFAULT


@pytest.mark.parametrize(
    "data",
    [
        b"not a wheel",
        wheel(requirement="deeptutor>=99"),
        wheel(requirement="other-package>=1"),
        wheel(extra=("../escape.py", "bad")),
        wheel(extra=("sitecustomize.py", "bad")),
        wheel(extra=(manager.NAMESPACE + "/native.so", "bad")),
    ],
)
def test_invalid_wheel_never_changes_installed_generation(data):
    manager.install(wheel())
    before = manager.read_state()
    with pytest.raises(ValueError):
        manager.install(data)
    assert manager.read_state() == before


def test_invalid_action_does_not_change_state():
    with pytest.raises(ValueError):
        manager.configure(extension="exec", enabled=True)
    assert manager.read_state() == manager.DEFAULT


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", ""),
        ("POST", "/download"),
        ("POST", "/install"),
        ("DELETE", ""),
        ("POST", "/restore"),
        ("PUT", "/quiz/enabled"),
    ],
)
def test_non_admin_cannot_manage_plugins(monkeypatch, method, path):
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    app = FastAPI()
    app.dependency_overrides[auth.require_auth] = lambda: SimpleNamespace(role="user")
    app.include_router(reading_plugins.router, prefix="/plugins")
    response = TestClient(app).request(method, "/plugins" + path, json={"enabled": True})
    assert response.status_code == 403
    assert manager.read_state() == manager.DEFAULT


def test_admin_upload_and_restore(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    app = FastAPI()
    app.dependency_overrides[auth.require_auth] = lambda: SimpleNamespace(role="admin")
    app.include_router(reading_plugins.router, prefix="/plugins")
    client = TestClient(app)
    response = client.post("/plugins/install", files={"file": ("reading.whl", wheel())})
    assert response.status_code == 200
    assert response.json()["restart_required"]
    assert client.post("/plugins/restore").json()["desired"]["mode"] == "builtin"


def test_pip_version_and_startup_choice_survive_settings_write(monkeypatch):
    dist = SimpleNamespace(
        version="0.1.0",
        entry_points=[
            SimpleNamespace(
                name=name, value=target, group="deeptutor.reading_extensions", load=lambda: object
            )
            for name, target in manager.EXTENSIONS.items()
        ],
    )
    monkeypatch.setattr(manager.metadata, "distribution", lambda _: dist)
    monkeypatch.setattr(manager, "ACTIVE_STATE", manager.read_state())
    assert manager.status()["active"]["version"] == "0.1.0"
    selected = manager.configure(extension="vocabulary", enabled=False)
    assert selected["desired"]["mode"] == "pip"
    # Existing process retains all three actions until restart.
    assert manager.load_overrides() == (dict.fromkeys(manager.EXTENSIONS, object), set())
    monkeypatch.setattr(manager, "ACTIVE_STATE", manager.read_state())
    assert manager.load_overrides()[1] == {"vocabulary"}


@pytest.mark.parametrize("valid_digest", [True, False])
def test_release_download_checks_digest_before_install(monkeypatch, valid_digest):
    import hashlib

    import httpx

    data = wheel()
    url = f"https://github.com/{manager.RELEASE_REPO}/releases/download/v0.1.0/{manager.NAMESPACE}-0.1.0-py3-none-any.whl"

    def handle(request):
        if request.url.host == "api.github.com":
            return httpx.Response(
                200,
                json={
                    "assets": [
                        {
                            "name": url.rsplit("/", 1)[1],
                            "browser_download_url": url,
                            "digest": "sha256:"
                            + (hashlib.sha256(data).hexdigest() if valid_digest else "0" * 64),
                        }
                    ]
                },
            )
        return httpx.Response(200, content=data)

    client = httpx.Client(transport=httpx.MockTransport(handle))
    monkeypatch.setattr(manager.httpx, "Client", lambda **_: client)
    if valid_digest:
        assert manager.download_latest()["desired"]["version"] == "0.1.0"
    else:
        with pytest.raises(ValueError, match="checksum"):
            manager.download_latest()
        assert manager.read_state() == manager.DEFAULT
