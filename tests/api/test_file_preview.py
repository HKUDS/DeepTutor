"""Office preview conversion and its local-file URL boundary."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from starlette.datastructures import QueryParams

from deeptutor.api.routers import file_preview, outputs
from deeptutor.multi_user import learning_access
from deeptutor.services import office_preview
from deeptutor.services.path_service import PathService


def _request(query: str = "") -> SimpleNamespace:
    return SimpleNamespace(query_params=QueryParams(query), headers={})


def test_preview_route_requires_authentication(monkeypatch) -> None:
    from deeptutor.api.main import app
    from deeptutor.api.routers import auth

    routes = [
        route for route in app.routes if getattr(route, "path", "") == "/api/file-preview/pdf"
    ]
    assert len(routes) == 2  # GET source and POST uploaded bytes
    assert all(
        any(dependency.call is auth.require_auth for dependency in route.dependant.dependencies)
        for route in routes
    )
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    response = TestClient(app).get(
        "/api/file-preview/pdf", params={"source": "/files/outputs/report.docx"}
    )
    assert response.status_code == 401


def test_source_url_must_be_local_and_workspace_scope_must_match(
    monkeypatch, tmp_path: Path
) -> None:
    source = tmp_path / "report.docx"
    source.write_bytes(b"office")
    seen: list[str] = []

    def resolve(path: str, _query: dict) -> tuple[Path, str]:
        seen.append(path)
        return source, source.name

    monkeypatch.setattr(file_preview, "_resolve_authorized_file", resolve)
    monkeypatch.setattr(file_preview, "_cache_dir", lambda: tmp_path / "cache")
    with pytest.raises(file_preview.HTTPException) as external:
        file_preview._source_path("https://elsewhere.test/report.docx", _request())
    assert external.value.status_code == 400
    with pytest.raises(file_preview.HTTPException) as conflict:
        file_preview._source_path(
            "/files/outputs/report.docx?dt_workspace=one", _request("dt_workspace=two")
        )
    assert conflict.value.status_code == 400
    assert file_preview._source_path(
        "/files/outputs/%E6%8A%A5%E5%91%8A.docx?dt_workspace=",
        _request("dt_workspace="),
    ) == (source, "report.docx", tmp_path / "cache")
    assert seen == ["/files/outputs/报告.docx"]


def test_source_allowlist_and_output_traversal(monkeypatch, tmp_path: Path) -> None:
    path_service = PathService(tmp_path)
    allowed = tmp_path / "user/workspace/chat/chat/turn-1/exec/report.docx"
    allowed.parent.mkdir(parents=True)
    allowed.write_bytes(b"office")
    outside = tmp_path / "etc/passwd"
    outside.parent.mkdir()
    outside.write_bytes(b"secret")
    monkeypatch.setattr(outputs, "_request_path_service", lambda: path_service)
    monkeypatch.setattr(outputs, "_resolve_partner_output", lambda _relative: None)
    monkeypatch.setattr(file_preview, "_cache_dir", lambda: tmp_path / "cache")

    resolved = file_preview._source_path(
        "/files/outputs/workspace/chat/chat/turn-1/exec/report.docx", _request()
    )
    assert resolved == (allowed, "report.docx", tmp_path / "cache")
    with pytest.raises(file_preview.HTTPException) as unsupported:
        file_preview._source_path("/etc/passwd", _request())
    assert unsupported.value.status_code == 400
    with pytest.raises(file_preview.HTTPException) as traversal:
        file_preview._source_path("/files/outputs/%2E%2E/%2E%2E/etc/passwd", _request())
    assert traversal.value.status_code == 404


def test_get_and_post_return_pdf(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "report.docx"
    source.write_bytes(b"office")
    monkeypatch.setattr(
        file_preview, "_resolve_authorized_file", lambda _path, _query: (source, source.name)
    )
    monkeypatch.setattr(file_preview, "_cache_dir", lambda: tmp_path / "cache")

    async def render(data: bytes, filename: str, _cache_dir: Path) -> bytes:
        assert data == b"office"
        assert filename == "report.docx"
        return b"%PDF-1.7\npreview"

    monkeypatch.setattr(file_preview, "render_office_pdf", render)
    app = FastAPI()
    app.include_router(file_preview.router, prefix="/api/file-preview")
    client = TestClient(app)

    fetched = client.get("/api/file-preview/pdf", params={"source": "/files/outputs/report.docx"})
    assert fetched.status_code == 200
    assert fetched.headers["content-type"] == "application/pdf"
    assert fetched.content.startswith(b"%PDF-")
    assert "inline" in fetched.headers["content-disposition"]

    uploaded = client.post(
        "/api/file-preview/pdf",
        files={"file": ("report.docx", b"office", "application/octet-stream")},
    )
    assert uploaded.status_code == 200
    assert uploaded.content == fetched.content

    async def unavailable(_data: bytes, _filename: str, _cache_dir: Path) -> bytes:
        raise office_preview.OfficePreviewUnavailable("LibreOffice is not installed")

    monkeypatch.setattr(file_preview, "render_office_pdf", unavailable)
    assert (
        client.get(
            "/api/file-preview/pdf", params={"source": "/files/outputs/report.docx"}
        ).status_code
        == 503
    )


def test_learner_preview_surface_matches_source(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "report.docx"
    source.write_bytes(b"office")
    monkeypatch.setattr(
        file_preview, "_resolve_authorized_file", lambda _path, _query: (source, source.name)
    )
    monkeypatch.setattr(file_preview, "_cache_dir", lambda: tmp_path / "cache")

    async def render(_data: bytes, _filename: str, _cache_dir: Path) -> bytes:
        return b"%PDF-1.7\npreview"

    monkeypatch.setattr(file_preview, "render_office_pdf", render)

    def reading_only(surface: str) -> None:
        if surface != "reading":
            raise PermissionError("Chat is not allowed")

    monkeypatch.setattr(learning_access, "assert_learning_surface", reading_only)
    app = FastAPI()
    app.include_router(file_preview.router, prefix="/api/file-preview")
    client = TestClient(app)
    assert (
        client.get(
            "/api/file-preview/pdf",
            params={"source": "/api/knowledge-bases/kb/files/report.docx"},
        ).status_code
        == 200
    )
    assert (
        client.get(
            "/api/file-preview/pdf",
            params={"source": "/api%2Fknowledge-bases/kb/files/report.docx"},
        ).status_code
        == 200
    )
    assert (
        client.get(
            "/api/file-preview/pdf",
            params={"source": "/files/attachments/session/item/report.docx"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/file-preview/pdf",
            files={"file": ("report.docx", b"office")},
        ).status_code
        == 403
    )


def test_converter_uses_isolated_profile_and_cached_pdf(monkeypatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(office_preview.shutil, "which", lambda _name: "/fake/soffice")

    def fake_popen(args: list[str], **_kwargs) -> SimpleNamespace:
        calls.append(args)
        assert args[1].startswith("-env:UserInstallation=file://")
        output = Path(args[args.index("--outdir") + 1])
        (output / "source.pdf").write_bytes(b"%PDF-1.7\npreview")
        return SimpleNamespace(returncode=0, communicate=lambda **_kwargs: (b"", b""))

    monkeypatch.setattr(office_preview.subprocess, "Popen", fake_popen)
    cache_dir = tmp_path / "cache"
    first = asyncio.run(office_preview.render_office_pdf(b"office", "report.docx", cache_dir))
    second = asyncio.run(office_preview.render_office_pdf(b"office", "report.docx", cache_dir))
    assert first == second == b"%PDF-1.7\npreview"
    assert len(calls) == 1
    assert len(list(cache_dir.glob("*.pdf"))) == 1


def test_converter_reports_missing_libreoffice_and_rejects_oversized_input(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(office_preview.shutil, "which", lambda _name: None)
    with pytest.raises(office_preview.OfficePreviewInvalid):
        asyncio.run(office_preview.render_office_pdf(b"x", "report.txt", tmp_path))
    with pytest.raises(office_preview.OfficePreviewUnavailable):
        asyncio.run(office_preview.render_office_pdf(b"x", "report.docx", tmp_path))
    with pytest.raises(office_preview.OfficePreviewInvalid):
        asyncio.run(
            office_preview.render_office_pdf(
                b"x" * (office_preview.MAX_OFFICE_BYTES + 1), "report.docx", tmp_path
            )
        )
