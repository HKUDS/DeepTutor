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

    Both distributions ship the configurable MCP tool surface. An extra-gated
    client would leave ordinary configured servers failing with
    ``ModuleNotFoundError`` on a plain install.
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


def test_pageindex_sdk_range_matches_every_install_surface() -> None:
    expected = "pageindex>=0.2.10,<0.3.0"
    with (REPOSITORY_ROOT / "pyproject.toml").open("rb") as file:
        root = tomllib.load(file)["project"]
    with (REPOSITORY_ROOT / "packaging" / "deeptutor-cli" / "pyproject.toml").open("rb") as file:
        cli_package = tomllib.load(file)["project"]

    assert root["dependencies"].count(expected) == 1
    assert root["optional-dependencies"]["cli"].count(expected) == 1
    assert cli_package["dependencies"].count(expected) == 1
    assert (REPOSITORY_ROOT / "requirements" / "cli.txt").read_text(
        encoding="utf-8"
    ).splitlines().count(expected) == 1


@pytest.mark.parametrize(
    "expected",
    [
        "loguru>=0.7.3,<1.0.0",
        "json-repair>=0.57.0,<1.0.0",
        "pyte>=0.8.1",
        "pdfplumber>=0.11.0,<0.11.8",
        "reportlab>=4.0.0",
    ],
)
def test_cli_runtime_dependencies_match_every_install_surface(expected: str) -> None:
    """CLI-only installs must include everything used by terminal workflows."""
    with (REPOSITORY_ROOT / "pyproject.toml").open("rb") as file:
        root = tomllib.load(file)["project"]
    with (REPOSITORY_ROOT / "packaging" / "deeptutor-cli" / "pyproject.toml").open("rb") as file:
        cli_package = tomllib.load(file)["project"]

    assert root["dependencies"].count(expected) == 1
    assert cli_package["dependencies"].count(expected) == 1
    requirement_lines = [
        line.split("#", 1)[0].strip()
        for line in (REPOSITORY_ROOT / "requirements" / "cli.txt")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert requirement_lines.count(expected) == 1
