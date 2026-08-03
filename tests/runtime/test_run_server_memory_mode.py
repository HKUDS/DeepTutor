from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from deeptutor.api import run_server


@pytest.fixture
def uvicorn_kwargs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    monkeypatch.setattr(run_server, "get_runtime_home", lambda: tmp_path)
    monkeypatch.setattr(run_server.os, "chdir", lambda _path: None)
    monkeypatch.setattr(run_server.uvicorn, "run", lambda *args, **kwargs: captured.update(kwargs))

    from deeptutor import logging as deeptutor_logging
    from deeptutor.runtime import mode
    from deeptutor.services import setup

    monkeypatch.setattr(deeptutor_logging, "configure_logging", lambda: None)
    monkeypatch.setattr(mode, "set_mode", lambda _mode: None)
    monkeypatch.setattr(setup, "get_backend_port", lambda _root: 8001)
    return captured


def test_run_server_disables_reload_by_default(
    monkeypatch: pytest.MonkeyPatch, uvicorn_kwargs: dict[str, Any]
) -> None:
    monkeypatch.delenv("DEEPTUTOR_DEV_RELOAD", raising=False)

    run_server.main()

    assert uvicorn_kwargs["reload"] is False
    assert uvicorn_kwargs["reload_excludes"] is None


def test_run_server_reload_remains_available_for_development(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    uvicorn_kwargs: dict[str, Any],
) -> None:
    monkeypatch.setenv("DEEPTUTOR_DEV_RELOAD", "true")
    (tmp_path / "data").mkdir()

    run_server.main()

    assert uvicorn_kwargs["reload"] is True
    assert str(tmp_path / "data") in uvicorn_kwargs["reload_excludes"]
