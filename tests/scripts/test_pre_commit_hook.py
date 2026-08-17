from __future__ import annotations

import os
from pathlib import Path
import subprocess


def test_hook_stops_when_repo_hygiene_fails(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    calls = tmp_path / "calls"
    fake_python = tmp_path / "python3"
    fake_python.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "$1" >> "{calls}"\n'
        'test "$1" != "scripts/check_repo_hygiene.py"\n',
        encoding="utf-8",
    )
    fake_python.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{tmp_path}{os.pathsep}{env['PATH']}"
    result = subprocess.run(
        ["sh", "scripts/hooks/pre-commit"],
        cwd=repo_root,
        env=env,
        check=False,
    )

    assert result.returncode != 0
    assert calls.read_text(encoding="utf-8").splitlines() == ["scripts/check_repo_hygiene.py"]
