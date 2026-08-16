from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


def test_api_import_keeps_optional_heavy_dependencies_cold() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    probe = """
import json
import sys

import deeptutor.api.main  # noqa: F401

heavy_roots = {
    "anthropic",
    "docx",
    "fitz",
    "graphrag",
    "llama_index",
    "matplotlib",
    "networkx",
    "numpy",
    "openpyxl",
    "pandas",
    "pptx",
    "pypdf",
}
loaded = sorted(name for name in heavy_roots if name in sys.modules)
print(json.dumps(loaded))
"""

    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=repo_root,
        capture_output=True,
        check=True,
        text=True,
    )

    assert json.loads(result.stdout) == []
