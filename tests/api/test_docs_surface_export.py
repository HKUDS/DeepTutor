"""Freshness gate for the committed docs surface artifact.

``docs/tests/docs_surface.json`` is generated from the real Typer CLI and
FastAPI app by ``scripts/export_docs_surface.py``, then committed so the
dependency-light doc contract tests can read it. Nothing regenerates it on its
own, so without this gate the artifact could silently drift from the code it
claims to describe.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

from scripts.export_docs_surface import render_surface

ROOT = Path(__file__).resolve().parents[2]


def test_committed_docs_surface_matches_the_live_app() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/export_docs_surface.py", "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=600,
    )

    assert result.returncode == 0, (
        "docs/tests/docs_surface.json no longer matches the live CLI/API surface. "
        "Regenerate it with `python scripts/export_docs_surface.py` and commit the "
        f"result.\n--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )


def test_render_surface_is_deterministic() -> None:
    """Two renders of the same live app must be byte-identical."""
    assert render_surface() == render_surface()
