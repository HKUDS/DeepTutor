"""PyInstaller entry point for the DeepTutor CLI.

Analysis must not target ``deeptutor_cli/main.py`` directly — that file uses
relative imports and fails with "attempted relative import with no known
parent package" when frozen as a bare script.

Frozen-process adaptations live only under ``packaging/pyinstaller/`` so the
library packages stay unchanged.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure packaging helpers import when running from a source checkout.
_PACKAGING_DIR = Path(__file__).resolve().parent
if str(_PACKAGING_DIR) not in sys.path:
    sys.path.insert(0, str(_PACKAGING_DIR))

from frozen_support import apply_frozen_patches, maybe_run_isolated_worker  # noqa: E402


def main() -> None:
    worker_code = maybe_run_isolated_worker()
    if worker_code is not None:
        raise SystemExit(worker_code)
    apply_frozen_patches()
    from deeptutor_cli.main import main as cli_main

    cli_main()


if __name__ == "__main__":
    main()
