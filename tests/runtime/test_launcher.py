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
