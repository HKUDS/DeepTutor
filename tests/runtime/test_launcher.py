from __future__ import annotations

import builtins
from pathlib import Path

import pytest

from deeptutor.runtime import launcher


class _FakeTty:
    def isatty(self) -> bool:
        return True


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
