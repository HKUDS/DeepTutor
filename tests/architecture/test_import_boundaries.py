from __future__ import annotations

from pathlib import Path
import subprocess
import sys


def test_architecture_boundaries() -> None:
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / "check_architecture.py"), "--root", str(root)],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
