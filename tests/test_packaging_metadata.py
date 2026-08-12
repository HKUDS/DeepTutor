"""Tests for dependency metadata shared by the published packages."""

from __future__ import annotations

from pathlib import Path
import tomllib

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "metadata_path",
    [
        REPOSITORY_ROOT / "pyproject.toml",
        REPOSITORY_ROOT / "packaging" / "deeptutor-cli" / "pyproject.toml",
    ],
)
def test_typer_dependency_does_not_request_removed_all_extra(metadata_path: Path) -> None:
    with metadata_path.open("rb") as file:
        dependencies = tomllib.load(file)["project"]["dependencies"]

    typer_requirements = [item for item in dependencies if item.startswith("typer")]
    assert typer_requirements == ["typer>=0.9.0"]
