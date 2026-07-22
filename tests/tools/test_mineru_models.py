from __future__ import annotations

from pathlib import Path
import threading
import time

import pytest

from deeptutor.services.parsing.engines.mineru import models as mineru_models
from deeptutor.services.parsing.engines.mineru.models import (
    ModelDownloadManager,
    model_env_overrides,
    resolve_models_downloader,
)

# ---------------------------------------------------------------------------
# Downloader resolution
# ---------------------------------------------------------------------------


def test_resolver_prefers_configured_cli_sibling(tmp_path: Path) -> None:
    bin_dir = tmp_path / "env" / "bin"
    bin_dir.mkdir(parents=True)
    cli = bin_dir / "mineru"
    cli.write_text("#!/bin/sh\n", encoding="utf-8")
    cli.chmod(0o755)
    downloader = bin_dir / "mineru-models-download"
    downloader.write_text("#!/bin/sh\n", encoding="utf-8")
    downloader.chmod(0o755)

    resolved = resolve_models_downloader(str(cli))
    assert resolved == {"found": True, "path": str(downloader)}


def test_resolver_reports_missing_sibling_no_path_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Even if PATH has the downloader, a configured CLI without a sibling
    # downloader is a miss — the configured env is authoritative.
    monkeypatch.setattr(
        mineru_models.shutil, "which", lambda cmd: "/usr/bin/mineru-models-download"
    )
    cli = tmp_path / "mineru"
    cli.write_text("#!/bin/sh\n", encoding="utf-8")
    cli.chmod(0o755)

    resolved = resolve_models_downloader(str(cli))
    assert resolved["found"] is False
    assert resolved["path"].endswith("mineru-models-download")


def test_resolver_falls_back_to_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        mineru_models.shutil, "which", lambda cmd: "/opt/bin/mineru-models-download"
    )
    assert resolve_models_downloader("") == {
        "found": True,
        "path": "/opt/bin/mineru-models-download",
    }

    monkeypatch.setattr(mineru_models.shutil, "which", lambda cmd: None)
    assert resolve_models_downloader("")["found"] is False


# ---------------------------------------------------------------------------
# Env overrides
# ---------------------------------------------------------------------------


def test_model_env_overrides_shapes() -> None:
    assert model_env_overrides("huggingface") == {"MINERU_MODEL_SOURCE": "huggingface"}
    assert model_env_overrides("huggingface", "https://hf-mirror.com/") == {
        "MINERU_MODEL_SOURCE": "huggingface",
        "HF_ENDPOINT": "https://hf-mirror.com",
    }
    # Endpoint is an HF-only concept; modelscope ignores it.
    assert model_env_overrides("modelscope", "https://hf-mirror.com") == {
        "MINERU_MODEL_SOURCE": "modelscope"
    }
    # Unknown source degrades to the default.
    assert model_env_overrides("weird")["MINERU_MODEL_SOURCE"] == "huggingface"


# ---------------------------------------------------------------------------
# Download job manager
# ---------------------------------------------------------------------------


class _FakeProc:
    def __init__(self, lines, returncode: int = 0):
        self.stdout = iter(lines)
        self._returncode = returncode
        self.terminated = False

    def wait(self) -> int:
        return -15 if self.terminated else self._returncode

    def poll(self):
        return None if not self.terminated else -15

    def terminate(self) -> None:
        self.terminated = True


def _wait_for_terminal(manager: ModelDownloadManager, timeout: float = 2.0) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = manager.status()["state"]
        if state != "running":
            return state
        time.sleep(0.01)
    return manager.status()["state"]


def test_manager_happy_path_and_cursor(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = ModelDownloadManager()
    monkeypatch.setattr(
        mineru_models.subprocess,
        "Popen",
        lambda *a, **k: _FakeProc(["downloading layout model...\n"]),
    )

    result = manager.start(
        downloader="/x/mineru-models-download",
        model_type="pipeline",
        source="huggingface",
    )
    assert result["ok"] is True
    assert _wait_for_terminal(manager) == "done"

    status = manager.status(0)
    assert status["lines"] == ["downloading layout model..."]
    assert status["message"] == "Download finished."
    # Cursor protocol: re-polling from next_cursor yields nothing new.
    assert manager.status(status["next_cursor"])["lines"] == []


def test_manager_nonzero_exit_is_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = ModelDownloadManager()
    monkeypatch.setattr(
        mineru_models.subprocess,
        "Popen",
        lambda *a, **k: _FakeProc(["boom\n"], returncode=3),
    )
    assert manager.start(downloader="/x/dl", model_type="pipeline", source="huggingface")["ok"]
    assert _wait_for_terminal(manager) == "failed"
    assert "code 3" in manager.status()["message"]


def test_manager_rejects_concurrent_start_and_cancels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = threading.Event()

    def blocking_lines():
        yield "starting\n"
        release.wait(timeout=5)

    proc = _FakeProc(blocking_lines())
    monkeypatch.setattr(mineru_models.subprocess, "Popen", lambda *a, **k: proc)

    manager = ModelDownloadManager()
    assert manager.start(downloader="/x/dl", model_type="all", source="modelscope")["ok"]
    # Busy: a second start is rejected while the first is running.
    busy = manager.start(downloader="/x/dl", model_type="pipeline", source="huggingface")
    assert busy["ok"] is False

    cancelled = manager.cancel()
    assert cancelled["ok"] is True
    release.set()
    assert _wait_for_terminal(manager) == "cancelled"


def test_manager_cancel_without_job() -> None:
    assert ModelDownloadManager().cancel()["ok"] is False
