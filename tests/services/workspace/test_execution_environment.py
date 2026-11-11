from __future__ import annotations

from pathlib import Path

from deeptutor.services.workspace.execution import prepare_workspace_execution_env


def test_execution_environment_forces_headless_matplotlib(tmp_path: Path) -> None:
    """A GUI backend would block on show() in the display-less exec sandbox.

    schemdraw's ``Drawing`` defaults to ``show=True``; its context manager
    calls ``fig.show()`` on exit even after the figure was saved. Without a
    non-interactive backend that call waits for a window server until the exec
    timeout kills the process, so the saved plot never reaches the user.
    """
    env = prepare_workspace_execution_env(tmp_path / "outputs" / "chat" / "s" / "turn")

    assert env["MPLBACKEND"] == "Agg"
