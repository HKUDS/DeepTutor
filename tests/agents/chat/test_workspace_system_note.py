"""The turn-workspace note must describe the host shell the model will get.

`exec` runs through PowerShell on Windows and a POSIX shell elsewhere, so the
note has to teach the matching way to write a script to a file — a Bash heredoc
is a syntax error in PowerShell, and the model would silently produce no file.
Everything else in the note is host-independent and must stay identical, which
is what keeps the two variants from drifting apart.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from deeptutor.agents.chat import agentic_pipeline
from deeptutor.agents.chat.agentic_pipeline import AgenticChatPipeline


@pytest.fixture
def note(monkeypatch: pytest.MonkeyPatch):
    def render(*, language: str, platform: str) -> str:
        monkeypatch.setattr(agentic_pipeline.sys, "platform", platform)
        monkeypatch.setattr(
            AgenticChatPipeline,
            "_workspace_key",
            staticmethod(lambda context: "session-1"),
        )
        monkeypatch.setattr(
            "deeptutor.services.path_service.get_path_service",
            lambda: SimpleNamespace(
                get_task_workspace=lambda *a, **k: Path("/tmp/ws"),
            ),
        )
        pipeline = SimpleNamespace(
            _exec_enabled=True,
            language=language,
            _workspace_key=lambda context: "session-1",
        )
        return AgenticChatPipeline._workspace_system_note(pipeline, object())

    return render


@pytest.mark.parametrize("language", ["en", "zh"])
def test_windows_note_teaches_powershell_not_heredoc(note, language: str) -> None:
    windows = note(language=language, platform="win32")
    assert "Set-Content" in windows
    assert "python gen.py" in windows
    # A Bash heredoc as the *instruction* is what breaks on Windows; the note
    # may name it only to tell the model not to use it.
    assert "python - <<'PY'" not in windows


@pytest.mark.parametrize("language", ["en", "zh"])
def test_posix_note_teaches_heredoc_and_never_powershell(note, language: str) -> None:
    posix = note(language=language, platform="linux")
    assert "python - <<'PY'" in posix
    assert "Set-Content" not in posix
    assert "PowerShell" not in posix


@pytest.mark.parametrize("language", ["en", "zh"])
def test_host_independent_guidance_is_identical(note, language: str) -> None:
    """Only the script-writing clause may differ between hosts."""
    windows = note(language=language, platform="win32")
    posix = note(language=language, platform="linux")
    for shared in ("/tmp/ws", "exec"):
        assert shared in windows and shared in posix
    tail = "不要粘贴原始 URL。" if language == "zh" else "do not paste raw URLs."
    assert windows.endswith(tail) and posix.endswith(tail)
    header = "[本轮工作区]" if language == "zh" else "[Turn workspace]"
    assert windows.startswith(header) and posix.startswith(header)


def test_note_is_empty_when_exec_is_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    pipeline = SimpleNamespace(_exec_enabled=False, language="en")
    assert AgenticChatPipeline._workspace_system_note(pipeline, object()) == ""
