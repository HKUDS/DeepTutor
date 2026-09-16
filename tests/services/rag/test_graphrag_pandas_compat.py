"""Regression tests for Pandas/Arrow extension registration in GraphRAG."""

from __future__ import annotations

import importlib
import os
from pathlib import Path
import subprocess
import sys

import pytest


def test_prepare_pandas_arrow_extensions_repairs_stale_registration() -> None:
    """A re-import after module removal must not hit ArrowKeyError."""
    pytest.importorskip("pandas", reason="pandas is required for this regression test")
    pytest.importorskip("pyarrow", reason="pyarrow is required for this regression test")
    root = Path(__file__).parents[3]
    script = """
import importlib
import sys

import pandas.core.arrays.arrow.extension_types

module_name = "pandas.core.arrays.arrow.extension_types"
del sys.modules[module_name]

from deeptutor.services.rag.pipelines.graphrag.pandas_compat import (
    prepare_pandas_arrow_extensions,
)

prepare_pandas_arrow_extensions()
importlib.import_module(module_name)
print("ok")
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(root), env.get("PYTHONPATH", "")) if part
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("ok")


def test_prepare_pandas_arrow_extensions_does_not_hide_unrelated_arrow_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only the known duplicate-registration error is recovered."""
    pytest.importorskip("pyarrow", reason="pyarrow is required for this regression test")

    from pyarrow.lib import ArrowKeyError

    from deeptutor.services.rag.pipelines.graphrag import pandas_compat

    def raise_unrelated_error(_name: str) -> None:
        raise ArrowKeyError("unrelated Arrow registry failure")

    monkeypatch.setattr(importlib, "import_module", raise_unrelated_error)

    with pytest.raises(ArrowKeyError, match="unrelated Arrow registry failure"):
        pandas_compat.prepare_pandas_arrow_extensions()
