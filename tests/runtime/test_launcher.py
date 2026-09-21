from __future__ import annotations

import builtins
import os
from pathlib import Path
import signal
import subprocess
import sys
from types import SimpleNamespace

import pytest

from deeptutor.runtime import launcher
from deeptutor.runtime import process as runtime_process
from deeptutor.runtime.home import validate_runtime_home
from deeptutor.services.app_update import UpdateJobStore, update_store_root


class _FakeTty:
    def isatty(self) -> bool:
        return True


class _AcceptedConnection:
    def __enter__(self) -> "_AcceptedConnection":
        return self

    def __exit__(self, *_args: object) -> None:
        return None


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


def test_launcher_hands_pending_update_to_worker(tmp_path: Path) -> None:
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
        launcher.urlrequest,
        "urlopen",
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


CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_PROCESS_GROUP = 0x200


def _windows_creation_constants(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(launcher.os, "name", "nt")
    monkeypatch.setattr(
        launcher.subprocess,
        "CREATE_NEW_PROCESS_GROUP",
        CREATE_NEW_PROCESS_GROUP,
        raising=False,
    )
    monkeypatch.setattr(
        launcher.subprocess,
        "CREATE_NO_WINDOW",
        CREATE_NO_WINDOW,
        raising=False,
    )


class _SilentThread:
    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def start(self) -> None:
        pass


def test_no_window_creationflags_is_zero_on_posix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(launcher.os, "name", "posix")
    assert launcher._no_window_creationflags() == 0


def test_no_window_creationflags_uses_create_no_window_on_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _windows_creation_constants(monkeypatch)
    assert launcher._no_window_creationflags() == CREATE_NO_WINDOW


@pytest.mark.skipif(os.name == "nt", reason="POSIX creationflags contract")
def test_posix_accepts_zero_creationflags_from_helper() -> None:
    flags = launcher._no_window_creationflags()
    assert flags == 0
    completed = subprocess.run([sys.executable, "-c", "pass"], check=True, creationflags=flags)
    assert completed.returncode == 0
    with pytest.raises(ValueError, match="creationflags"):
        subprocess.run([sys.executable, "-c", "pass"], creationflags=1)


def test_spawn_hides_windows_console_for_backend_and_frontend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class _Process:
        pid = 4242
        stdout = iter(())

    def fake_popen(command, **kwargs):
        captured.update(kwargs)
        return _Process()

    _windows_creation_constants(monkeypatch)
    monkeypatch.setattr(launcher.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(launcher.threading, "Thread", _SilentThread)

    proc = launcher._spawn(["python"], cwd=tmp_path, env={}, name="backend")

    assert proc.process.pid == 4242
    assert captured["creationflags"] == CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
    assert "start_new_session" not in captured


def test_spawn_keeps_posix_start_new_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class _Process:
        pid = 4242
        stdout = iter(())

    def fake_popen(command, **kwargs):
        captured.update(kwargs)
        return _Process()

    monkeypatch.setattr(launcher.os, "name", "posix")
    monkeypatch.setattr(launcher.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(launcher.threading, "Thread", _SilentThread)
    monkeypatch.setattr(launcher, "_get_pgid", lambda _pid: None)

    launcher._spawn(["python"], cwd=tmp_path, env={}, name="frontend")

    assert captured.get("start_new_session") is True
    assert "creationflags" not in captured


@pytest.mark.skipif(os.name == "nt", reason="live POSIX spawn path")
def test_spawn_on_linux_does_not_pass_creationflags(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    real_popen = launcher.subprocess.Popen

    def wrapping_popen(*args, **kwargs):
        captured.update(kwargs)
        return real_popen(*args, **kwargs)

    monkeypatch.setattr(launcher.subprocess, "Popen", wrapping_popen)
    proc = launcher._spawn(
        [sys.executable, "-c", "pass"],
        cwd=tmp_path,
        env=os.environ.copy(),
        name="probe",
    )
    assert proc.process.wait(timeout=5) == 0
    assert captured.get("start_new_session") is True
    assert "creationflags" not in captured


def test_send_tree_signal_hides_windows_taskkill_console(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_run(*_args, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(returncode=0)

    _windows_creation_constants(monkeypatch)
    monkeypatch.setattr(launcher.subprocess, "run", fake_run)

    launcher._send_tree_signal(14168, None, signal.SIGTERM)

    assert calls[0]["creationflags"] == CREATE_NO_WINDOW
    assert calls[0]["stdout"] is subprocess.DEVNULL
    assert calls[0]["stderr"] is subprocess.DEVNULL


def test_send_tree_signal_does_not_spawn_taskkill_on_posix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    killed: list[tuple[int, object]] = []
    monkeypatch.setattr(launcher.os, "name", "posix")
    monkeypatch.setattr(launcher.os, "killpg", lambda pgid, sig: killed.append((pgid, sig)))
    monkeypatch.setattr(
        launcher.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("taskkill must not run on POSIX"),
    )

    launcher._send_tree_signal(11, 22, signal.SIGTERM)

    assert killed == [(22, signal.SIGTERM)]


def test_windows_port_and_pid_probes_hide_console_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], int]] = []

    def fake_run(cmd, **kwargs):
        calls.append((list(cmd), kwargs.get("creationflags", 0)))
        if cmd[0] == "netstat":
            return SimpleNamespace(
                stdout="  TCP    127.0.0.1:8001    0.0.0.0:0    LISTENING    4242\n",
                returncode=0,
            )
        return SimpleNamespace(stdout='"python.exe","4242","Services","0","12 K"\n', returncode=0)

    _windows_creation_constants(monkeypatch)
    monkeypatch.setattr(launcher.shutil, "which", lambda name: name)
    monkeypatch.setattr(launcher.subprocess, "run", fake_run)

    listeners = launcher._port_listeners_windows(8001)

    assert listeners == [(4242, "python.exe")]
    assert calls == [
        (["netstat", "-ano", "-p", "tcp"], CREATE_NO_WINDOW),
        (["tasklist", "/FI", "PID eq 4242", "/FO", "CSV", "/NH"], CREATE_NO_WINDOW),
    ]


def test_ensure_web_dependencies_hides_windows_npm_console(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "web"
    source.mkdir()
    (source / "package-lock.json").write_text("{}", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_run(cmd, cwd, **kwargs):
        captured["cmd"] = list(cmd)
        captured["kwargs"] = kwargs
        (source / "node_modules").mkdir()
        return _CompletedProcess(0)

    _windows_creation_constants(monkeypatch)
    monkeypatch.setattr(launcher.subprocess, "run", fake_run)

    launcher._ensure_web_dependencies(source, "npm")

    assert captured["cmd"] == ["npm", "ci"]
    assert captured["kwargs"]["creationflags"] == CREATE_NO_WINDOW


def test_ensure_web_dependencies_passes_zero_creationflags_on_posix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "web"
    source.mkdir()
    captured: dict[str, object] = {}

    def fake_run(cmd, cwd, **kwargs):
        captured["kwargs"] = kwargs
        return _CompletedProcess(0)

    monkeypatch.setattr(launcher.os, "name", "posix")
    monkeypatch.setattr(launcher.subprocess, "run", fake_run)

    launcher._ensure_web_dependencies(source, "npm")

    assert captured["kwargs"]["creationflags"] == 0


def test_source_production_build_hides_windows_npm_console(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "web"
    source.mkdir()
    (source / "package.json").write_text('{"scripts":{"build":"next build"}}', encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_run(command, cwd, env, **kwargs):
        captured["cmd"] = list(command)
        captured["kwargs"] = kwargs
        dist = source / launcher.SOURCE_PRODUCTION_DIST_DIR
        (dist / "standalone").mkdir(parents=True, exist_ok=True)
        (dist / "BUILD_ID").write_text("build-1", encoding="utf-8")
        (dist / "standalone" / "server.js").write_text("", encoding="utf-8")
        return _CompletedProcess(0)

    _windows_creation_constants(monkeypatch)
    monkeypatch.setattr(launcher.subprocess, "run", fake_run)
    monkeypatch.setattr(launcher, "_source_build_fingerprint", lambda *_a, **_k: "fp")
    monkeypatch.setattr(launcher, "_prepare_source_standalone", lambda path: path)

    launcher._ensure_source_production_build(
        source,
        "npm",
        api_base="http://localhost:8001",
        auth_enabled=False,
    )

    assert captured["cmd"] == ["npm", "run", "build"]
    assert captured["kwargs"]["creationflags"] == CREATE_NO_WINDOW
