"""The backend must import from the same code installation as its launcher."""

from __future__ import annotations

import json
from pathlib import Path
import socket
from types import SimpleNamespace
from urllib.request import ProxyHandler, build_opener

import pytest

from deeptutor.runtime import launcher


class _BackendObserved(Exception):
    pass


def _write_app(root: Path, version: str) -> None:
    api = root / "deeptutor" / "api"
    api.mkdir(parents=True)
    (root / "deeptutor" / "__init__.py").write_text(f"__version__ = {version!r}\n")
    (api / "__init__.py").write_text("")
    (api / "main.py").write_text(
        "import json\n"
        "from deeptutor import __version__\n"
        "async def app(scope, receive, send):\n"
        "    if scope['type'] == 'lifespan':\n"
        "        while True:\n"
        "            event = await receive()\n"
        "            if event['type'] == 'lifespan.startup':\n"
        "                await send({'type': 'lifespan.startup.complete'})\n"
        "            elif event['type'] == 'lifespan.shutdown':\n"
        "                await send({'type': 'lifespan.shutdown.complete'})\n"
        "                return\n"
        "    body = json.dumps({'version': __version__, 'module_file': __file__}).encode()\n"
        "    await send({'type': 'http.response.start', 'status': 200,\n"
        "                'headers': [(b'content-type', b'application/json')]})\n"
        "    await send({'type': 'http.response.body', 'body': body})\n"
    )


@pytest.mark.parametrize("backend_workers", [1, 2])
def test_backend_imports_launcher_installation_despite_stale_runtime_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, backend_workers: int
) -> None:
    pytest.importorskip("uvicorn")
    from deeptutor.services import config, setup

    # The live launcher already resolved this installation. The runtime home
    # may still contain an older source archive after a wheel upgrade.
    installed = tmp_path / "installed code"
    home = tmp_path / "old runtime home"
    _write_app(installed, "1.7.2")
    _write_app(home, "1.6.15")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        backend_port = listener.getsockname()[1]
    settings_dir = home / "data" / "user" / "settings"
    settings = config.LaunchSettings(
        backend_port=backend_port,
        frontend_port=3782,
        language="en",
        source="test",
        settings_dir=settings_dir,
        interface_json_path=settings_dir / "interface.json",
        system_json_path=settings_dir / "system.json",
    )

    monkeypatch.setattr(launcher, "PACKAGE_ROOT", installed)
    monkeypatch.setenv(launcher.DEEPTUTOR_HOME_ENV, str(home))
    # Match the detached launcher's existing protection. Uvicorn's default
    # app-dir reintroduces cwd independently of Python's safe-path setting.
    monkeypatch.setenv("PYTHONSAFEPATH", "1")
    monkeypatch.setenv("PYTHONPATH", str(installed))
    monkeypatch.delenv(launcher.DETACHED_WORKER_ENV, raising=False)
    monkeypatch.delenv(launcher.DETACHED_TOKEN_ENV, raising=False)
    monkeypatch.setattr(launcher, "_relax_console_encoding", lambda: None)
    monkeypatch.setattr(launcher, "_reset_runtime_singletons", lambda: None)
    monkeypatch.setattr(config, "ensure_runtime_settings_files", lambda: None)
    monkeypatch.setattr(config, "load_launch_settings", lambda _home: settings)
    monkeypatch.setattr(
        config, "load_system_settings", lambda: {"backend_workers": backend_workers}
    )
    monkeypatch.setattr(config, "export_runtime_settings_to_env", lambda **_kwargs: {})
    monkeypatch.setattr(config, "load_auth_settings", lambda: {"enabled": False})
    monkeypatch.setattr(config, "get_ws_max_size", lambda: 1024)
    monkeypatch.setattr(
        config,
        "get_runtime_settings_service",
        lambda: SimpleNamespace(settings_derived_keys=lambda: set()),
    )
    monkeypatch.setattr(setup, "init_user_directories", lambda _home: None)
    monkeypatch.setattr(launcher, "resolve_language", lambda: "en")
    monkeypatch.setattr(launcher, "print_banner", lambda **_kwargs: None)
    monkeypatch.setattr(launcher, "_log", lambda _message: None)
    monkeypatch.setattr(
        launcher,
        "_resolve_frontend",
        lambda *_args, **_kwargs: launcher.FrontendRuntime("packaged", ["node"], home),
    )
    monkeypatch.setattr(launcher, "_detect_existing_source_frontend", lambda _runtime: None)
    monkeypatch.setattr(launcher, "_resolve_port_conflicts", lambda **_kwargs: (backend_port, 3782))
    monkeypatch.setattr(launcher, "_install_signal_handlers", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(launcher.atexit, "register", lambda _callback: None)
    monkeypatch.setattr(launcher, "_fail_restarted_update", lambda *_args: False)

    spawn = launcher._spawn
    wait_for_http = launcher._wait_for_http
    observed: dict = {}

    def spawn_loopback(command, *, cwd, env, name):
        assert name == "backend"
        assert cwd == home
        command = list(command)
        command[command.index("--host") + 1] = "127.0.0.1"
        return spawn(command, cwd=cwd, env=env, name=name)

    def observe_backend(**kwargs):
        wait_for_http(**{**kwargs, "timeout": 15.0})
        # The launcher command, real Uvicorn import, worker startup, HTTP
        # exchange and process cleanup run unchanged; no Node server is needed.
        with build_opener(ProxyHandler({})).open(kwargs["url"], timeout=5) as response:
            observed.update(json.load(response))
        raise _BackendObserved()

    monkeypatch.setattr(launcher, "_spawn", spawn_loopback)
    monkeypatch.setattr(launcher, "_wait_for_http", observe_backend)
    with pytest.raises(_BackendObserved):
        launcher.start(home, open_browser=False)

    assert observed["version"] == "1.7.2"
    assert (
        Path(observed["module_file"]).resolve()
        == (installed / "deeptutor" / "api" / "main.py").resolve()
    )
