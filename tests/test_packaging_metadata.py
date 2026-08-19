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


@pytest.mark.parametrize(
    "metadata_path",
    [
        REPOSITORY_ROOT / "pyproject.toml",
        REPOSITORY_ROOT / "packaging" / "deeptutor-cli" / "pyproject.toml",
    ],
)
def test_mcp_client_is_a_core_dependency(metadata_path: Path) -> None:
    """`mcp` must install by default, not only via an extra (issue #792).

    Both distributions ship ``deeptutor.services.mcp``, and the connection
    manager overlays the built-in PageIndex MCP server onto the config whenever
    a PageIndex API key is set. That happens on a plain install, so an
    extra-gated ``mcp`` leaves the connection task dying with
    ``ModuleNotFoundError`` on every turn.
    """
    with metadata_path.open("rb") as file:
        dependencies = tomllib.load(file)["project"]["dependencies"]

    mcp_requirements = [item for item in dependencies if item.split(">")[0].strip() == "mcp"]
    assert mcp_requirements == ["mcp>=1.26.0,<2.0.0"]


def test_partners_extra_does_not_redeclare_the_core_mcp_client() -> None:
    """The `partners` extra is IM channel SDKs only; `mcp` is core now."""
    with (REPOSITORY_ROOT / "pyproject.toml").open("rb") as file:
        extras = tomllib.load(file)["project"]["optional-dependencies"]

    assert not [item for item in extras["partners"] if item.split(">")[0].strip() == "mcp"]


def test_requirements_mirror_the_core_mcp_client() -> None:
    """Docker/CI installs read requirements/, which must agree with pyproject."""
    requirements = REPOSITORY_ROOT / "requirements"
    cli_text = (requirements / "cli.txt").read_text(encoding="utf-8")
    partners_text = (requirements / "partners.txt").read_text(encoding="utf-8")

    # cli.txt mirrors the core dependency set, so the client belongs there...
    assert "mcp>=1.26.0,<2.0.0" in cli_text
    # ...and partners.txt inherits it transitively rather than redeclaring it.
    assert "-r server.txt" in partners_text
    assert "mcp>=" not in partners_text
