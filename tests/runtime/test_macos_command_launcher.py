from __future__ import annotations

from pathlib import Path
import shutil
import subprocess


def test_macos_command_launcher_forwards_home_and_arguments(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[2] / "start_deeptutor.command"
    launcher = tmp_path / source.name
    shutil.copy2(source, launcher)

    python = tmp_path / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text(
        """#!/bin/sh
if [ "$1" = "-c" ]; then
    exit 0
fi
printf '%s\\n' "$@"
""",
        encoding="utf-8",
    )
    python.chmod(0o755)

    result = subprocess.run(
        [str(launcher), "--dev"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.splitlines()[-6:] == [
        "-m",
        "deeptutor_cli.main",
        "start",
        "--home",
        str(tmp_path),
        "--dev",
    ]
