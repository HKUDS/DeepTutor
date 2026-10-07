from __future__ import annotations

import builtins
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import logging
from pathlib import Path
import signal
import subprocess
from threading import Thread
from types import SimpleNamespace

import pytest

from deeptutor.runtime import launcher
from deeptutor.runtime import process as runtime_process
from deeptutor.runtime.home import validate_runtime_home
from deeptutor.services.app_update import UpdateJob, UpdateJobStore, update_store_root


class _FakeTty:
    def isatty(self) -> bool:
        return True


class _AcceptedConnection:
    def __enter__(self) -> "_AcceptedConnection":
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def test_loopback_health_checks_ignore_configured_proxy(monkeypatch) -> None:
    """A proxy must not make healthy local backend/frontend probes fail."""

    def serve(status: int) -> tuple[ThreadingHTTPServer, Thread]:
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                self.send_response(status)
                self.end_headers()

            def log_message(self, *_args: object) -> None:
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        return server, worker

    ready, ready_worker = serve(204)
    proxy, proxy_worker = serve(502)
    url = f"http://127.0.0.1:{ready.server_port}/health"
    monkeypatch.setattr(
        launcher.urlrequest,
        "getproxies",
        lambda: {"http": f"http://127.0.0.1:{proxy.server_port}"},
    )
    monkeypatch.setattr(launcher.urlrequest, "proxy_bypass", lambda _host: False)
    monkeypatch.setattr(launcher.urlrequest, "_opener", None)
    try:
        # Prove this test environment really directs ordinary urllib traffic
        # through the proxy; a false green here would miss the regression.
        with pytest.raises(launcher.urlerror.HTTPError) as excinfo:
            launcher.urlrequest.urlopen(url, timeout=1)
        assert excinfo.value.code == 502

        assert launcher._http_ready(url, timeout=1)
        launcher._wait_for_http(
            name="Backend",
            url=url,
            process=None,
            timeout=2,
            env_name=launcher.BACKEND_READY_TIMEOUT_ENV,
            should_stop=lambda: False,
        )
    finally:
        for server, worker in ((ready, ready_worker), (proxy, proxy_worker)):
            server.shutdown()
            server.server_close()
            worker.join(timeout=1)


def test_port_probe_detects_ipv6_only_loopback_listener(monkeypatch) -> None:
    """Unix launchers may bind only to ::1 (issue #1096)."""
    attempts: list[tuple[str, int]] = []

    def fake_create_connection(address, timeout):
        host, port = address
        attempts.append((host, port))
        if host == "::1":
            return _AcceptedConnection()
        raise ConnectionRefusedError

    monkeypatch.setattr(launcher.socket, "create_connection", fake_create_connection)

    assert launcher._port_accepts_connection(3782)
    assert attempts == [("127.0.0.1", 3782), ("::1", 3782)]


def test_packaged_web_cache_replaces_next_public_placeholders(tmp_path: Path) -> None:
    packaged = tmp_path / "pkg"
    (packaged / ".next" / "static").mkdir(parents=True)
    (packaged / "server.js").write_text(
        "const api='__NEXT_PUBLIC_API_BASE_PLACEHOLDER__';",
        encoding="utf-8",
    )
    (packaged / ".next" / "static" / "app.js").write_text(
        "auth='__NEXT_PUBLIC_AUTH_ENABLED_PLACEHOLDER__'",
        encoding="utf-8",
    )

    runtime = launcher._copy_packaged_web_if_needed(
        packaged,
        home=tmp_path / "home",
        api_base="http://localhost:8001",
        auth_enabled=True,
    )

    assert (runtime / "server.js").read_text(encoding="utf-8") == (
        "const api='http://localhost:8001';"
    )
    assert "auth='true'" in (runtime / ".next" / "static" / "app.js").read_text(encoding="utf-8")


def test_runtime_home_rejects_project_data_paths(monkeypatch, tmp_path: Path) -> None:
    package_root = tmp_path / "package"
    monkeypatch.setattr("deeptutor.runtime.home.PACKAGE_ROOT", package_root)

    with pytest.raises(ValueError, match="Invalid DeepTutor runtime home"):
        validate_runtime_home(package_root / "data")
    with pytest.raises(ValueError, match="Invalid DeepTutor runtime home"):
        validate_runtime_home(package_root / "data" / "user")


def test_start_does_not_create_nested_data_tree(monkeypatch, tmp_path: Path) -> None:
    package_root = tmp_path / "package"
    bad_home = package_root / "data" / "user"
    monkeypatch.setattr("deeptutor.runtime.home.PACKAGE_ROOT", package_root)
    monkeypatch.setattr(launcher, "get_runtime_home", lambda _home=None: bad_home)

    with pytest.raises(SystemExit, match="Invalid DeepTutor runtime home"):
        launcher.start(bad_home)

    assert not bad_home.exists()


def test_launcher_hands_pending_update_to_worker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from deeptutor.services import app_update

    monkeypatch.setattr(app_update, "running_under_systemd_service", lambda: False)
    store = UpdateJobStore(update_store_root(tmp_path))
    pending = store.create(current_version="1.6.1", target_version="1.7.0")
    launched: list[Path] = []

    handed_off = launcher._handoff_pending_update(
        tmp_path,
        restart_argv=["start", "--home", str(tmp_path.resolve())],
        worker_launcher=launched.append,
    )

    assert handed_off is True
    assert launched == [store.root]
    job = store.load()
    assert job.id == pending.id
    assert job.status == "handoff"
    assert job.restart_home == str(tmp_path.resolve())


def test_launcher_keeps_systemd_service_running_for_pending_update(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from deeptutor.services import app_update

    store = UpdateJobStore(update_store_root(tmp_path))
    store.create(current_version="1.6.1", target_version="1.7.0")
    monkeypatch.setattr(app_update, "running_under_systemd_service", lambda: True)
    launched: list[Path] = []

    assert (
        launcher._handoff_pending_update(
            tmp_path,
            restart_argv=["start", "--home", str(tmp_path.resolve())],
            worker_launcher=launched.append,
        )
        is False
    )
    assert launched == []
    assert store.load().status == "failed"
    assert not store.active_path.exists()


def test_launcher_handoff_failure_still_logged_when_marking_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A handoff failure must leave a trace even if mark_failed fails too."""

    from deeptutor.services import app_update

    monkeypatch.setattr(app_update, "running_under_systemd_service", lambda: False)
    store = UpdateJobStore(update_store_root(tmp_path))
    store.create(current_version="1.6.1", target_version="1.7.0")

    def failing_worker_launcher(_root: Path) -> None:
        raise RuntimeError("worker spawn boom")

    def broken_mark_failed(_self: UpdateJobStore, _job_id: str, _error: str) -> UpdateJob:
        raise OSError("state write boom")

    monkeypatch.setattr(UpdateJobStore, "mark_failed", broken_mark_failed)
    logs: list[str] = []
    monkeypatch.setattr(launcher, "_log", logs.append)

    assert (
        launcher._handoff_pending_update(
            tmp_path,
            restart_argv=["start", "--home", str(tmp_path.resolve())],
            worker_launcher=failing_worker_launcher,
        )
        is False
    )
    assert logs, "double handoff failure vanished without any log"
    trace = " | ".join(logs)
    assert "Launcher handoff failed" in trace
    assert "worker spawn boom" in trace
    assert "state write boom" in trace


def test_launcher_completes_update_only_after_restart(tmp_path: Path) -> None:
    store = UpdateJobStore(update_store_root(tmp_path))
    pending = store.create(current_version="1.6.1", target_version="1.7.0")
    store.prepare_handoff(
        pending.id,
        home=tmp_path,
        restart_argv=["start", "--home", str(tmp_path.resolve())],
    )
    store.mark_running(pending.id)
    store.mark_restarting(pending.id)

    assert launcher._complete_restarted_update(tmp_path) is True
    assert store.load().status == "succeeded"


def test_packaged_web_cache_refreshes_when_public_settings_change(tmp_path: Path) -> None:
    packaged = tmp_path / "pkg"
    (packaged / ".next").mkdir(parents=True)
    (packaged / "server.js").write_text(
        "const api='__NEXT_PUBLIC_API_BASE_PLACEHOLDER__';",
        encoding="utf-8",
    )
    home = tmp_path / "home"

    first = launcher._copy_packaged_web_if_needed(
        packaged,
        home=home,
        api_base="http://localhost:8001",
        auth_enabled=False,
    )
    second = launcher._copy_packaged_web_if_needed(
        packaged,
        home=home,
        api_base="https://api.example",
        auth_enabled=False,
    )

    assert first == second
    assert "https://api.example" in (second / "server.js").read_text(encoding="utf-8")


def test_detect_existing_source_frontend_from_next_dev_lock(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "web"
    lock = source / ".next" / "dev" / "lock"
    lock.parent.mkdir(parents=True)
    lock.write_text(
        '{"pid":12345,"port":3999,"appUrl":"http://localhost:3999"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(launcher, "_is_pid_alive", lambda pid: pid == 12345)
    monkeypatch.setattr(launcher, "_port_accepts_connection", lambda port: False)

    existing = launcher._detect_existing_source_frontend(
        launcher.FrontendRuntime("source", [], source)
    )

    assert existing is not None
    assert existing.url == "http://localhost:3999"
    assert existing.port == 3999
    assert existing.pid == 12345
    assert existing.lock_path == lock


def test_detect_existing_source_frontend_ignores_stale_lock(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "web"
    lock = source / ".next" / "dev" / "lock"
    lock.parent.mkdir(parents=True)
    lock.write_text(
        '{"pid":12345,"port":3999,"appUrl":"http://localhost:3999"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(launcher, "_is_pid_alive", lambda pid: False)
    monkeypatch.setattr(launcher, "_port_accepts_connection", lambda port: False)

    existing = launcher._detect_existing_source_frontend(
        launcher.FrontendRuntime("source", [], source)
    )

    assert existing is None


def test_resolve_port_conflicts_passthrough_when_free(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(launcher, "_port_accepts_connection", lambda port: False)

    result = launcher._resolve_port_conflicts(
        backend_port=8000,
        frontend_port=3784,
        check_frontend=True,
        settings_dir=tmp_path,
    )

    assert result == (8000, 3784)


def test_resolve_port_conflicts_non_tty_exits_with_message(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(launcher, "_port_accepts_connection", lambda port: port == 8000)
    monkeypatch.setattr(launcher, "_port_listeners", lambda port: [(123, "python uvicorn")])
    monkeypatch.setattr(launcher.sys, "stdin", None)

    with pytest.raises(SystemExit) as excinfo:
        launcher._resolve_port_conflicts(
            backend_port=8000,
            frontend_port=3784,
            check_frontend=True,
            settings_dir=tmp_path,
        )

    assert "8000" in str(excinfo.value)


def test_resolve_port_conflicts_kill_option_frees_port(tmp_path: Path, monkeypatch) -> None:
    occupied = {8000}
    killed: list[int] = []

    def fake_kill(pid, pgid, sig):
        killed.append(pid)
        occupied.discard(8000)

    monkeypatch.setattr(launcher, "_port_accepts_connection", lambda port: port in occupied)
    monkeypatch.setattr(launcher, "_port_listeners", lambda port: [(123, "python uvicorn")])
    monkeypatch.setattr(launcher, "_send_tree_signal", fake_kill)
    monkeypatch.setattr(launcher.sys, "stdin", _FakeTty())
    monkeypatch.setattr(builtins, "input", lambda prompt="": "2")

    result = launcher._resolve_port_conflicts(
        backend_port=8000,
        frontend_port=3784,
        check_frontend=True,
        settings_dir=tmp_path,
    )

    assert result == (8000, 3784)
    assert killed == [123]


def test_resolve_port_conflicts_change_option_prompts_and_persists(
    tmp_path: Path, monkeypatch
) -> None:
    saved: dict[str, int] = {}

    def fake_persist(settings_dir, backend_port, frontend_port):
        saved["backend"] = backend_port
        saved["frontend"] = frontend_port
        return settings_dir / "system.json"

    answers = iter(["1", "8002", "3785"])

    monkeypatch.setattr(launcher, "_port_accepts_connection", lambda port: port == 8000)
    monkeypatch.setattr(launcher, "_port_listeners", lambda port: [(123, "python uvicorn")])
    monkeypatch.setattr(launcher, "_persist_ports", fake_persist)
    monkeypatch.setattr(launcher.sys, "stdin", _FakeTty())
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(answers))

    result = launcher._resolve_port_conflicts(
        backend_port=8000,
        frontend_port=3784,
        check_frontend=True,
        settings_dir=tmp_path,
    )

    assert result == (8002, 3785)
    assert saved == {"backend": 8002, "frontend": 3785}


class _RecordingStream:
    """Stand-in for a console stream that records ``reconfigure`` calls."""

    def __init__(self, *, raises: Exception | None = None) -> None:
        self.calls: list[dict[str, object]] = []
        self._raises = raises

    def reconfigure(self, **kwargs: object) -> None:
        self.calls.append(kwargs)
        if self._raises is not None:
            raise self._raises


def test_relax_console_encoding_replaces_unencodable_output() -> None:
    """A legacy Windows code page can't encode the frontend's ``✓`` banner; the
    relay thread used to die on it and the session went silent (issue #702)."""
    stdout = _RecordingStream()
    stderr = _RecordingStream()

    launcher._relax_console_encoding((stdout, stderr))

    assert stdout.calls == [{"errors": "replace"}]
    assert stderr.calls == [{"errors": "replace"}]


def test_relax_console_encoding_tolerates_odd_streams() -> None:
    """Redirected / already-detached streams must not break startup."""
    launcher._relax_console_encoding((object(), _RecordingStream(raises=ValueError("detached"))))


class _CompletedProcess:
    def __init__(self, returncode: int) -> None:
        self.returncode = returncode


def test_ensure_web_dependencies_runs_npm_ci_when_a_lockfile_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fresh source clone has no ``web/node_modules`` and used to die on Node's
    MODULE_NOT_FOUND before the dev server ever started (issue #709)."""
    source = tmp_path / "web"
    source.mkdir()
    (source / "package-lock.json").write_text("{}", encoding="utf-8")
    calls: list[tuple[list[str], Path]] = []

    def _run(cmd, cwd, **_kwargs):
        calls.append((list(cmd), Path(cwd)))
        (source / "node_modules").mkdir()
        return _CompletedProcess(0)

    monkeypatch.setattr(launcher.subprocess, "run", _run)

    launcher._ensure_web_dependencies(source, "npm")

    assert calls == [(["npm", "ci"], source)]


def test_ensure_web_dependencies_falls_back_to_npm_install_without_a_lockfile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "web"
    source.mkdir()
    calls: list[list[str]] = []
    monkeypatch.setattr(
        launcher.subprocess,
        "run",
        lambda cmd, cwd, **_kw: (calls.append(list(cmd)), _CompletedProcess(0))[1],
    )

    launcher._ensure_web_dependencies(source, "npm")

    assert calls == [["npm", "install"]]


def test_ensure_web_dependencies_is_a_no_op_once_installed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The launcher resolves the frontend more than once per start."""
    source = tmp_path / "web"
    (source / "node_modules").mkdir(parents=True)

    def _boom(*_args, **_kwargs):
        raise AssertionError("npm must not run when node_modules is present")

    monkeypatch.setattr(launcher.subprocess, "run", _boom)

    launcher._ensure_web_dependencies(source, "npm")


def test_ensure_web_dependencies_surfaces_a_failed_install(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "web"
    source.mkdir()
    (source / "package-lock.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(launcher.subprocess, "run", lambda *_a, **_kw: _CompletedProcess(1))

    with pytest.raises(SystemExit) as excinfo:
        launcher._ensure_web_dependencies(source, "npm")

    assert "npm ci" in str(excinfo.value)


def test_source_frontend_defaults_to_cached_production_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "web"
    (source / "node_modules").mkdir(parents=True)
    builds: list[tuple[Path, str, str, bool]] = []

    monkeypatch.setattr(launcher, "_packaged_web_dir", lambda: None)
    monkeypatch.setattr(launcher, "_source_web_dir", lambda _home: source)
    monkeypatch.setattr(launcher.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(
        launcher,
        "_ensure_source_production_build",
        lambda path, npm, *, api_base, auth_enabled: builds.append(
            (path, npm, api_base, auth_enabled)
        ),
    )

    runtime = launcher._resolve_frontend(
        tmp_path,
        3782,
        api_base="http://localhost:8001",
        auth_enabled=True,
    )

    assert runtime.kind == "source-production"
    standalone = source / launcher.SOURCE_PRODUCTION_DIST_DIR / "standalone"
    assert runtime.command == ["/bin/node", str(standalone / "server.js")]
    assert runtime.cwd == standalone
    assert builds == [(source, "/bin/npm", "http://localhost:8001", True)]


def test_source_frontend_dev_mode_is_explicit_and_skips_production_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "web"
    (source / "node_modules").mkdir(parents=True)

    monkeypatch.setattr(launcher, "_packaged_web_dir", lambda: None)
    monkeypatch.setattr(launcher, "_source_web_dir", lambda _home: source)
    monkeypatch.setattr(launcher.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(
        launcher,
        "_ensure_source_production_build",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("--dev must not build the production frontend")
        ),
    )

    runtime = launcher._resolve_frontend(
        tmp_path,
        3782,
        api_base="http://localhost:8001",
        auth_enabled=False,
        dev=True,
    )

    assert runtime.kind == "source"
    assert runtime.command == ["/bin/npm", "run", "dev", "--", "--port", "3782"]


def test_source_production_build_is_reused_until_an_input_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "web"
    source.mkdir()
    (source / "package.json").write_text('{"scripts":{"build":"next build"}}', encoding="utf-8")
    next_env = source / "next-env.d.ts"
    next_env.write_text("// developer dist types\n", encoding="utf-8")
    app = source / "app"
    app.mkdir()
    page = app / "page.tsx"
    page.write_text("export default function Page() { return null; }", encoding="utf-8")
    calls: list[tuple[list[str], Path, str]] = []

    def _run(command, cwd, env, **_kwargs):
        calls.append((list(command), Path(cwd), env["DEEPTUTOR_NEXT_DIST_DIR"]))
        next_env.write_text("// production dist types\n", encoding="utf-8")
        dist = source / launcher.SOURCE_PRODUCTION_DIST_DIR
        (dist / "standalone").mkdir(parents=True, exist_ok=True)
        (dist / "BUILD_ID").write_text(f"build-{len(calls)}", encoding="utf-8")
        (dist / "standalone" / "server.js").write_text("", encoding="utf-8")
        return _CompletedProcess(0)

    monkeypatch.setattr(launcher.subprocess, "run", _run)

    for _ in range(2):
        launcher._ensure_source_production_build(
            source,
            "npm",
            api_base="http://localhost:8001",
            auth_enabled=False,
        )

    page.write_text("export default function Page() { return <main />; }", encoding="utf-8")
    launcher._ensure_source_production_build(
        source,
        "npm",
        api_base="http://localhost:8001",
        auth_enabled=False,
    )

    assert calls == [
        (["npm", "run", "build"], source, launcher.SOURCE_PRODUCTION_DIST_DIR),
        (["npm", "run", "build"], source, launcher.SOURCE_PRODUCTION_DIST_DIR),
    ]
    assert next_env.read_text(encoding="utf-8") == "// developer dist types\n"


@pytest.mark.parametrize("resolved_backend_port", [8001, 8123])
def test_start_uses_ipv4_loopback_for_frontend_proxy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    resolved_backend_port: int,
) -> None:
    from deeptutor.services import config as config_module
    from deeptutor.services import setup as setup_module

    settings_dir = tmp_path / "data" / "user" / "settings"
    settings = config_module.LaunchSettings(
        backend_port=8001,
        frontend_port=3782,
        language="en",
        source="test",
        settings_dir=settings_dir,
        interface_json_path=settings_dir / "interface.json",
        system_json_path=settings_dir / "system.json",
    )
    captured_envs: dict[str, dict[str, str]] = {}

    monkeypatch.setattr(launcher, "_relax_console_encoding", lambda: None)
    monkeypatch.setattr(launcher, "_reset_runtime_singletons", lambda: None)
    monkeypatch.setattr(config_module, "ensure_runtime_settings_files", lambda: None)
    monkeypatch.setattr(config_module, "load_launch_settings", lambda _home: settings)
    monkeypatch.setattr(
        config_module,
        "export_runtime_settings_to_env",
        lambda **_kwargs: {},
    )
    monkeypatch.setattr(config_module, "load_auth_settings", lambda: {"enabled": False})
    monkeypatch.setattr(config_module, "get_ws_max_size", lambda: 1024)
    monkeypatch.setattr(setup_module, "init_user_directories", lambda _home: None)
    monkeypatch.setattr(launcher, "resolve_language", lambda: "en")
    monkeypatch.setattr(launcher, "print_banner", lambda **_kwargs: None)
    monkeypatch.setattr(launcher, "_log", lambda _message: None)
    monkeypatch.setenv("DEEPTUTOR_NEXT_DIST_DIR", ".next-inherited")
    monkeypatch.setenv(launcher.DETACHED_WORKER_ENV, "1")
    monkeypatch.setenv(launcher.DETACHED_TOKEN_ENV, "secret-token")
    monkeypatch.setattr(
        launcher,
        "_resolve_frontend",
        lambda *_args, **_kwargs: launcher.FrontendRuntime("source-production", ["node"], tmp_path),
    )
    monkeypatch.setattr(launcher, "_detect_existing_source_frontend", lambda _runtime: None)
    monkeypatch.setattr(
        launcher,
        "_resolve_port_conflicts",
        lambda **_kwargs: (resolved_backend_port, 3782),
    )
    monkeypatch.setattr(launcher, "_install_signal_handlers", lambda _callback, **_kwargs: None)
    monkeypatch.setattr(launcher.atexit, "register", lambda _callback: None)
    monkeypatch.setattr(launcher, "_wait_for_http", lambda **_kwargs: None)
    monkeypatch.setattr(launcher, "_terminate", lambda _process: None)

    def _capture_spawn(_command, *, cwd, env, name):
        assert cwd == tmp_path
        captured_envs[name] = dict(env)
        if name == "backend":
            return launcher.ManagedProcess("backend", object(), None)
        assert name == "frontend"
        raise RuntimeError("captured launch environment")

    monkeypatch.setattr(launcher, "_spawn", _capture_spawn)

    with pytest.raises(RuntimeError, match="captured launch environment"):
        launcher.start(tmp_path)

    assert captured_envs["frontend"]["DEEPTUTOR_API_BASE_URL"] == (
        f"http://127.0.0.1:{resolved_backend_port}"
    )
    assert "DEEPTUTOR_NEXT_DIST_DIR" not in captured_envs["backend"]
    assert "DEEPTUTOR_NEXT_DIST_DIR" not in captured_envs["frontend"]
    assert launcher.DETACHED_WORKER_ENV not in captured_envs["backend"]
    assert launcher.DETACHED_TOKEN_ENV not in captured_envs["backend"]


def test_foreground_signal_handlers_keep_windows_ctrl_c(monkeypatch) -> None:
    recorded: list[tuple[object, object]] = []
    monkeypatch.setattr(launcher.signal, "SIGINT", 2, raising=False)
    monkeypatch.setattr(launcher.signal, "SIGTERM", 15, raising=False)
    monkeypatch.setattr(launcher.signal, "SIGHUP", None, raising=False)
    monkeypatch.setattr(launcher.signal, "SIGBREAK", 21, raising=False)
    monkeypatch.setattr(launcher.signal, "SIG_IGN", object())
    monkeypatch.setattr(
        launcher.signal,
        "signal",
        lambda sig, handler: recorded.append((sig, handler)),
    )

    launcher._install_signal_handlers(lambda _name: None)

    assert any(
        sig == launcher.signal.SIGINT and handler is not launcher.signal.SIG_IGN
        for sig, handler in recorded
    )


def test_detached_windows_signal_handlers_ignore_spurious_sigint(monkeypatch) -> None:
    recorded: list[tuple[object, object]] = []
    monkeypatch.setattr(launcher.signal, "SIGINT", 2, raising=False)
    monkeypatch.setattr(launcher.signal, "SIGTERM", 15, raising=False)
    monkeypatch.setattr(launcher.signal, "SIGHUP", None, raising=False)
    monkeypatch.setattr(launcher.signal, "SIGBREAK", 21, raising=False)
    monkeypatch.setattr(launcher.signal, "SIG_IGN", object())
    monkeypatch.setattr(
        launcher.signal,
        "signal",
        lambda sig, handler: recorded.append((sig, handler)),
    )

    launcher._install_signal_handlers(lambda _name: None, ignore_sigint=True)

    assert (launcher.signal.SIGINT, launcher.signal.SIG_IGN) in recorded
    assert not any(
        sig == launcher.signal.SIGINT and handler is not launcher.signal.SIG_IGN
        for sig, handler in recorded
    )


def test_windows_pid_probe_uses_native_query_not_os_kill(monkeypatch) -> None:
    probed: list[int] = []
    monkeypatch.setattr(runtime_process.os, "name", "nt")
    monkeypatch.setattr(
        runtime_process,
        "_is_windows_process_alive",
        lambda pid: probed.append(pid) or True,
    )
    monkeypatch.setattr(
        runtime_process.os,
        "kill",
        lambda *_args: pytest.fail("os.kill(pid, 0) is destructive on Windows"),
    )

    assert runtime_process.is_process_alive(4242) is True
    assert probed == [4242]


def test_open_frontend_in_browser_is_best_effort(monkeypatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url) or True)

    launcher._open_frontend_in_browser("http://localhost:3782")
    assert opened == ["http://localhost:3782"]

    def fail_to_open(_url: str) -> bool:
        raise RuntimeError("no browser")

    monkeypatch.setattr("webbrowser.open", fail_to_open)
    launcher._open_frontend_in_browser("http://localhost:3782")


def test_launch_detached_uses_a_separate_windows_process_group(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    class _Process:
        pid = 4242

    def fake_popen(command, *, stdout, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        captured["log_name"] = stdout.name
        return _Process()

    monkeypatch.setattr(launcher, "_is_pid_alive", lambda _pid: False)
    monkeypatch.setattr(launcher.sys, "platform", "win32")
    monkeypatch.setattr(launcher.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200, raising=False)
    monkeypatch.setattr(launcher.subprocess, "DETACHED_PROCESS", 0x8, raising=False)
    monkeypatch.setattr(launcher.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(launcher, "_log", lambda _message: None)

    launcher._launch_detached(tmp_path, dev=True, open_browser=False)

    paths = launcher._detached_launcher_paths(tmp_path)
    state = launcher._read_detached_state(paths)
    assert state is not None
    assert state["pid"] == 4242
    assert state["status"] == "starting"
    assert state["token"]
    assert captured["command"][-2:] == ["--dev", "--no-browser"]
    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["creationflags"] == 0x208
    assert kwargs["env"][launcher.DETACHED_WORKER_ENV] == "1"
    assert kwargs["env"][launcher.DETACHED_TOKEN_ENV] == state["token"]
    assert captured["log_name"] == str(paths.log)


def test_stop_requests_only_the_registered_detached_launcher(
    monkeypatch,
    tmp_path: Path,
) -> None:
    paths = launcher._detached_launcher_paths(tmp_path)
    launcher._write_detached_state(
        paths,
        {"version": 1, "token": "launch-token", "pid": 4242, "status": "ready"},
    )
    monkeypatch.setattr(launcher, "get_runtime_home", lambda _home=None: tmp_path)
    monkeypatch.setattr(launcher, "validate_runtime_home", lambda _home: None)
    monkeypatch.setattr(launcher, "resolve_language", lambda: "en")
    monkeypatch.setattr(launcher, "_log", lambda _message: None)
    monkeypatch.setattr(
        launcher,
        "_is_pid_alive",
        lambda _pid: not paths.stop.exists(),
    )

    assert launcher.stop(tmp_path, timeout=0.5) is True
    assert not paths.state.exists()
    assert not paths.stop.exists()


def test_ready_timeout_is_overridable_for_slow_hardware(monkeypatch) -> None:
    """An ARM board with a workspace to migrate can need past 60s (#1435).

    The launcher killed a backend that was still initialising and let the
    supervisor restart it into the same wall, so the wait has to be a property
    of the machine rather than a constant.
    """
    monkeypatch.setenv(launcher.BACKEND_READY_TIMEOUT_ENV, "180")
    assert launcher._ready_timeout(launcher.BACKEND_READY_TIMEOUT_ENV, 60) == 180

    for unusable in ("", "   ", "soon", "0", "-5"):
        monkeypatch.setenv(launcher.BACKEND_READY_TIMEOUT_ENV, unusable)
        assert launcher._ready_timeout(launcher.BACKEND_READY_TIMEOUT_ENV, 60) == 60

    monkeypatch.delenv(launcher.BACKEND_READY_TIMEOUT_ENV, raising=False)
    assert launcher._ready_timeout(launcher.BACKEND_READY_TIMEOUT_ENV, 60) == 60


def test_ready_timeout_failure_names_the_override(monkeypatch) -> None:
    """A bare "did not become ready in 60s" left the reporter nothing to do."""
    process = SimpleNamespace(process=SimpleNamespace(poll=lambda: None))
    clock = iter([0.0, 0.0, 999.0])
    monkeypatch.setattr(launcher.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(launcher.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        launcher._LOOPBACK_OPENER,
        "open",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("refused")),
    )

    with pytest.raises(RuntimeError) as excinfo:
        launcher._wait_for_http(
            name="Backend",
            url="http://127.0.0.1:65535/",
            process=process,
            timeout=60,
            env_name=launcher.BACKEND_READY_TIMEOUT_ENV,
            should_stop=lambda: False,
        )

    assert launcher.BACKEND_READY_TIMEOUT_ENV in str(excinfo.value)


def test_windows_children_and_console_tools_allocate_no_console(
    monkeypatch, tmp_path: Path
) -> None:
    """Nothing the console-less detached worker starts may open a window.

    Empty console windows flashed on the desktop for every probe, and the one
    Windows gave the node child was a real hazard: closing it delivered
    CTRL_C_EXIT to node, which the launcher read as its frontend exiting and
    answered by stopping the backend — the whole app died from a window close
    (#1501).
    """
    monkeypatch.setattr(launcher.os, "name", "nt")
    monkeypatch.setattr(launcher.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200, raising=False)
    monkeypatch.setattr(launcher.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    runs: list[dict[str, object]] = []
    popens: list[dict[str, object]] = []

    class _Completed:
        returncode = 0
        stdout = ""

    def fake_run(command, **kwargs):
        runs.append({"command": command, "kwargs": kwargs})
        return _Completed()

    class _Process:
        pid = 4242
        stdout = None

    def fake_popen(command, **kwargs):
        popens.append({"command": command, "kwargs": kwargs})
        return _Process()

    monkeypatch.setattr(launcher.subprocess, "run", fake_run)
    monkeypatch.setattr(launcher.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(launcher.threading, "Thread", lambda **_kwargs: _NoopThread())
    monkeypatch.setattr(launcher.shutil, "which", lambda name: name)

    launcher._spawn(["node", "server.js"], cwd=tmp_path, env={}, name="frontend")
    launcher._send_tree_signal(4242, None, launcher.KILL_SIGNAL)
    launcher._port_listeners_windows(3782)
    launcher._ensure_web_dependencies(tmp_path, "npm")

    assert popens[0]["kwargs"]["creationflags"] == 0x200 | 0x08000000
    assert [run["command"][0] for run in runs] == ["taskkill", "netstat", "npm"]
    for run in runs:
        assert run["kwargs"]["creationflags"] == 0x08000000, run["command"]


class _NoopThread:
    def start(self) -> None:
        return None


@pytest.mark.parametrize("probe", ["netstat", "tasklist", "lsof", "ps"])
def test_process_probes_tolerate_non_utf8_output(monkeypatch, probe: str) -> None:
    """A localized utility must not crash or hide a listener in UTF-8 mode."""
    import subprocess
    import sys

    run = subprocess.run
    outputs = {
        "netstat": b"\xbb localized heading\n  TCP  127.0.0.1:3782  0.0.0.0:0  LISTENING  123\n",
        "tasklist": b'"python.exe","123","\xbb session","1","0 K"\n',
        "lsof": b"\xbb diagnostic\np123\n",
        "ps": b"node next-server \xbb\n",
    }

    for name in outputs:
        if name != probe:
            outputs[name] = outputs[name].replace(b"\xbb", b"localized")

    def run_probe(args, **kwargs):
        # Use a real child pipe, with UTF-8 decoding as in the reported crash.
        kwargs["encoding"] = "utf-8"
        return run(
            [sys.executable, "-c", f"import sys; sys.stdout.buffer.write({outputs[args[0]]!r})"],
            **kwargs,
        )

    monkeypatch.setattr(launcher.shutil, "which", lambda name: name)
    monkeypatch.setattr(launcher.subprocess, "run", run_probe)
    if probe in {"netstat", "tasklist"}:
        assert launcher._port_listeners_windows(3782) == [(123, "python.exe")]
    else:
        monkeypatch.setattr(launcher, "os", SimpleNamespace(name="posix"))
        if probe == "lsof":
            assert launcher._port_listeners(3782) == [(123, "node next-server localized")]
        else:
            assert launcher._process_command(123) == "node next-server \ufffd"


@pytest.mark.parametrize("platform", ["nt", "posix"])
def test_port_listeners_tolerate_missing_stdout(monkeypatch, platform: str) -> None:
    """A failed subprocess reader may leave stdout unset on Windows."""
    monkeypatch.setattr(launcher, "os", SimpleNamespace(name=platform))
    monkeypatch.setattr(launcher.shutil, "which", lambda name: name)
    monkeypatch.setattr(
        launcher.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout=None)
    )
    assert launcher._port_listeners(3782) == []


class _StubbornPopen:
    """Popen stand-in that stays alive until a fake signal lets it exit."""

    def __init__(self, *, pid: int = 4242) -> None:
        self.pid = pid
        self.exited = False

    def poll(self) -> int | None:
        return 0 if self.exited else None

    def wait(self, timeout: float | None = None) -> int:
        if not self.exited:
            raise subprocess.TimeoutExpired(cmd="backend", timeout=timeout)
        return 0


def test_terminate_warns_when_both_signal_rounds_fail(
    monkeypatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A child no signal reaches must surface every failed round."""
    child = _StubbornPopen()
    proc = launcher.ManagedProcess(name="backend", process=child, pgid=4242)
    sent: list[int] = []

    def fake_send(pid, pgid, sig):
        sent.append(sig)
        # Neither round is delivered: SIGTERM is refused, SIGKILL vanishes.
        raise PermissionError("operation not permitted")

    monkeypatch.setattr(launcher, "_send_tree_signal", fake_send)

    with caplog.at_level(logging.WARNING, logger="deeptutor.runtime.launcher"):
        launcher._terminate(proc)

    assert sent == [signal.SIGTERM, launcher.KILL_SIGNAL]
    warnings = [record.getMessage() for record in caplog.records]
    assert any("SIGTERM" in message for message in warnings)
    assert any("SIGKILL" in message for message in warnings)


def test_terminate_warns_on_sigterm_but_accepts_kill_escalation(
    monkeypatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The ladder keeps its shape: refused SIGTERM, working SIGKILL, done."""
    child = _StubbornPopen()
    proc = launcher.ManagedProcess(name="backend", process=child, pgid=4242)

    def fake_send(pid, pgid, sig):
        if sig == launcher.KILL_SIGNAL:
            child.exited = True
            return
        raise PermissionError("operation not permitted")

    monkeypatch.setattr(launcher, "_send_tree_signal", fake_send)

    with caplog.at_level(logging.WARNING, logger="deeptutor.runtime.launcher"):
        launcher._terminate(proc)

    assert child.exited is True
    warnings = [record.getMessage() for record in caplog.records]
    assert any("SIGTERM" in message for message in warnings)
    assert not any("SIGKILL" in message for message in warnings)


def test_terminate_skips_absent_or_exited_child(
    monkeypatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Nothing to stop means no signal and no warning."""
    sent: list[int] = []

    def fake_send(pid, pgid, sig):
        sent.append(sig)

    monkeypatch.setattr(launcher, "_send_tree_signal", fake_send)
    exited = _StubbornPopen()
    exited.exited = True

    with caplog.at_level(logging.WARNING, logger="deeptutor.runtime.launcher"):
        launcher._terminate(None)
        launcher._terminate(launcher.ManagedProcess(name="web", process=exited, pgid=None))

    assert sent == []
    assert caplog.records == []


def test_signal_target_treats_already_gone_target_as_terminated(
    monkeypatch, caplog: pytest.LogCaptureFixture
) -> None:
    """ESRCH means the target exited on its own; that is not a failure."""

    def fake_send(pid, pgid, sig):
        raise ProcessLookupError()

    monkeypatch.setattr(launcher, "_send_tree_signal", fake_send)

    with caplog.at_level(logging.WARNING, logger="deeptutor.runtime.launcher"):
        launcher._signal_target(123, None, signal.SIGTERM, target="port 8000 listener")

    assert caplog.records == []


def test_windows_taskkill_failures_surface_but_missing_processes_do_not(
    monkeypatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A failing taskkill must be logged; one that found no process must not."""
    monkeypatch.setattr(launcher, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(launcher, "_no_window_kwargs", lambda: {})
    codes: list[int] = []
    monkeypatch.setattr(
        launcher.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=codes.pop(0)),
    )

    with caplog.at_level(logging.WARNING, logger="deeptutor.runtime.launcher"):
        for code in (1, 0, 128):
            codes.append(code)
            launcher._signal_target(7, None, signal.SIGTERM, target="backend (pid=7)")

    warnings = [record.getMessage() for record in caplog.records]
    assert len(warnings) == 1
    assert "SIGTERM" in warnings[0]
    assert "taskkill" in (caplog.records[0].exc_text or "")


def test_kill_port_listeners_isolates_one_targets_sigterm_failure(
    monkeypatch, caplog: pytest.LogCaptureFixture
) -> None:
    """One unreachable listener must not spare the others or hide itself."""
    occupied = {8000}

    def fake_send(pid, pgid, sig):
        if pid == 123:
            raise PermissionError("operation not permitted")
        occupied.discard(8000)

    monkeypatch.setattr(launcher, "_send_tree_signal", fake_send)
    monkeypatch.setattr(launcher, "_port_accepts_connection", lambda port: port in occupied)

    with caplog.at_level(logging.WARNING, logger="deeptutor.runtime.launcher"):
        launcher._kill_port_listeners({8000: [(123, "python uvicorn"), (456, "node")]})

    assert occupied == set()
    assert any("123" in record.getMessage() for record in caplog.records)


def test_kill_port_listeners_reports_kill_round_failures_per_target(
    monkeypatch, caplog: pytest.LogCaptureFixture
) -> None:
    """SIGTERM-ignoring listeners escalate; KILL failures stay per-target."""
    occupied = {8000}
    sent: list[tuple[int, int]] = []
    clock = {"now": 0.0}

    def fake_send(pid, pgid, sig):
        sent.append((pid, sig))
        if sig == launcher.KILL_SIGNAL and pid == 123:
            raise OSError("no such process")
        # pid 456 accepts both signals; zombie 123 keeps holding the port.

    def fake_sleep(seconds: float) -> None:
        clock["now"] += seconds

    monkeypatch.setattr(launcher, "_send_tree_signal", fake_send)
    monkeypatch.setattr(launcher, "_port_accepts_connection", lambda port: port in occupied)
    monkeypatch.setattr(launcher.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(launcher.time, "sleep", fake_sleep)

    with caplog.at_level(logging.WARNING, logger="deeptutor.runtime.launcher"):
        launcher._kill_port_listeners({8000: [(123, "python uvicorn"), (456, "node")]})

    assert (123, signal.SIGTERM) in sent
    assert (456, signal.SIGTERM) in sent
    assert (123, launcher.KILL_SIGNAL) in sent
    assert (456, launcher.KILL_SIGNAL) in sent
    assert any("SIGKILL" in record.getMessage() for record in caplog.records)
