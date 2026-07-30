"""The pipeline's half of a CLI app call: where it runs, and where its files land.

A CLI app is given its working directory by the pipeline, exactly as ``exec`` is.
That is not a stylistic choice — the directory has to be one ``/api/outputs`` will
serve from, so the file an app produced becomes a link the reader can open. These
tests pin that the injection happens for a ``cli_*`` name and that the directory
it picks is one the path policy actually publishes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.agents.chat.agentic_pipeline import AgenticChatPipeline
from deeptutor.core.context import UnifiedContext
from deeptutor.services.path_service import PathService


def _augment(tool_name: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict:
    service = PathService(workspace_root=tmp_path)
    monkeypatch.setattr("deeptutor.services.path_service.get_path_service", lambda: service)
    pipeline = AgenticChatPipeline.__new__(AgenticChatPipeline)
    monkeypatch.setattr(
        AgenticChatPipeline, "_current_user_id", lambda self: "u_ada", raising=False
    )
    context = UnifiedContext(session_id="s1", user_message="render it", metadata={"turn_id": "t-1"})
    return pipeline._augment_tool_kwargs(tool_name, {"args": ["render"]}, context)


def test_a_cli_app_call_is_given_a_workdir_and_a_writable_mount(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    kwargs = _augment("cli_blender", monkeypatch, tmp_path)

    workdir = kwargs["_sandbox_workdir"]
    assert workdir.endswith("/cli")
    assert Path(workdir).is_dir(), "the app cannot write into a directory nobody created"
    assert kwargs["_sandbox_user_id"] == "u_ada"
    mount = kwargs["_sandbox_mounts"][0]
    assert mount.read_only is False
    assert mount.host_path == mount.sandbox_path == workdir


def test_every_app_shares_one_directory_per_turn(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """So the model can render with one app and post-process with another."""
    first = _augment("cli_blender", monkeypatch, tmp_path)["_sandbox_workdir"]
    second = _augment("cli_imagemagick", monkeypatch, tmp_path)["_sandbox_workdir"]
    assert first == second


def test_a_cli_app_does_not_get_the_exec_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Separate directories keep an app's output distinguishable from a shell
    session's, which matters because both are published."""
    assert (
        _augment("cli_blender", monkeypatch, tmp_path)["_sandbox_workdir"]
        != _augment("exec", monkeypatch, tmp_path)["_sandbox_workdir"]
    )


def test_a_file_written_there_is_publicly_servable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The injection and the path policy have to agree. If they drift, an app
    writes a file that renders as a broken link."""
    kwargs = _augment("cli_blender", monkeypatch, tmp_path)
    produced = Path(kwargs["_sandbox_workdir"]) / "out.png"
    produced.write_bytes(b"\x89PNG\r\n\x1a\n")

    service = PathService(workspace_root=tmp_path)
    assert service.is_public_output_path(produced)


def test_a_private_suffix_in_that_directory_is_still_not_served(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    kwargs = _augment("cli_blender", monkeypatch, tmp_path)
    secret = Path(kwargs["_sandbox_workdir"]) / "notes.db"
    secret.write_bytes(b"sqlite")

    service = PathService(workspace_root=tmp_path)
    assert not service.is_public_output_path(secret)


def test_an_unrelated_tool_is_not_handed_a_sandbox(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The branch keys off the ``cli_`` prefix; a tool merely containing it must
    not pick up a workdir it never asked for."""
    kwargs = _augment("rag", monkeypatch, tmp_path)
    assert "_sandbox_workdir" not in kwargs
