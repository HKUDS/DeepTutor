"""Regression gates for the import-cheap built-in descriptors."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
import subprocess
import sys

from deeptutor.runtime.bootstrap.builtin_capabilities import BUILTIN_CAPABILITY_SPECS
from deeptutor.tools.builtin_specs import BUILTIN_TOOL_SPECS


def test_builtin_tool_descriptors_match_implementations() -> None:
    for spec in BUILTIN_TOOL_SPECS:
        assert spec.create().name == spec.name


def test_builtin_capability_descriptors_match_implementations() -> None:
    for name, spec in BUILTIN_CAPABILITY_SPECS.items():
        module_name, class_name = spec.class_path.rsplit(":", 1)
        actual = getattr(importlib.import_module(module_name), class_name).manifest
        expected = spec.manifest
        assert actual.name == name
        for field in (
            "description",
            "stages",
            "tools_used",
            "cli_aliases",
            "config_defaults",
        ):
            assert getattr(actual, field) == getattr(expected, field), (name, field)


def test_builtin_catalog_imports_keep_implementations_cold() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    probe = """
import json
import sys

import deeptutor.capabilities.registry
import deeptutor.runtime.registry.capability_registry
import deeptutor.runtime.registry.tool_registry

forbidden = (
    "deeptutor.agents.chat.agentic_pipeline",
    "deeptutor.capabilities.solve.loop",
    "deeptutor.capabilities.mastery.loop",
    "deeptutor.visualizers.loop_capability",
)
print(json.dumps([name for name in forbidden if name in sys.modules]))
"""
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=repo_root,
        capture_output=True,
        check=True,
        text=True,
    )
    assert json.loads(result.stdout) == []
