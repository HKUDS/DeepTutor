"""Static plugin frontend contract and filesystem boundary tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deeptutor.plugins.frontend import (
    FrontendPageError,
    parse_frontend_page_manifest,
    resolve_frontend_page_asset,
)


def _page() -> dict:
    return {
        "schema_version": "deeptutor.plugin-frontend-page/v1",
        "entry": "index.html",
        "assets": ["app.js", "index.html"],
    }


def _package(tmp_path: Path) -> Path:
    root = tmp_path / "package"
    root.mkdir()
    (root / "index.html").write_text("<html></html>", encoding="utf-8")
    (root / "app.js").write_text("export {}", encoding="utf-8")
    return root


def test_frontend_page_manifest_requires_explicit_asset_closure() -> None:
    page = parse_frontend_page_manifest(_page())

    assert page.entry == "index.html"
    assert page.assets == ("app.js", "index.html")

    raw = _page()
    raw["entry"] = "../index.html"
    with pytest.raises(FrontendPageError, match="traversal"):
        parse_frontend_page_manifest(raw)

    raw = _page()
    raw["assets"] = ["index.html", "app.exe"]
    with pytest.raises(FrontendPageError, match="unsupported file type"):
        parse_frontend_page_manifest(raw)


def test_frontend_asset_resolution_serves_only_declared_regular_files(
    tmp_path: Path,
) -> None:
    root = _package(tmp_path)
    (root / "secret.txt").write_text("secret", encoding="utf-8")
    page = parse_frontend_page_manifest(_page())

    assert resolve_frontend_page_asset(page, root, "app.js").name == "app.js"
    with pytest.raises(FrontendPageError, match="not declared"):
        resolve_frontend_page_asset(page, root, "secret.txt")
    with pytest.raises(FrontendPageError, match="not declared"):
        resolve_frontend_page_asset(page, root, "../deeptutor.plugin.json")


def test_frontend_asset_resolution_rejects_symlinks(tmp_path: Path) -> None:
    root = _package(tmp_path)
    outside = tmp_path / "outside.js"
    outside.write_text("outside", encoding="utf-8")
    (root / "app.js").unlink()
    (root / "app.js").symlink_to(outside)
    page = parse_frontend_page_manifest(_page())

    with pytest.raises(FrontendPageError, match="symlinks"):
        resolve_frontend_page_asset(page, root, "index.html")
