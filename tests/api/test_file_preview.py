"""Office preview conversion and its local-file URL boundary."""

from __future__ import annotations

import asyncio
import hashlib
from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from starlette.datastructures import QueryParams

from deeptutor.api.routers import file_preview, outputs
from deeptutor.multi_user import learning_access
from deeptutor.services import office_preview, pptx_fonts
from deeptutor.services.path_service import PathService


def _request(query: str = "") -> SimpleNamespace:
    return SimpleNamespace(query_params=QueryParams(query), headers={})


def _file_preview_routes(app):
    """Materialize lazily-included routers (new-fastapi ``_IncludedRouter``).

    Recent FastAPI turns ``include_router`` into lazy wrappers carrying the
    prefix and router-level dependencies in ``include_context``; flatten them
    the same way ``tests/video_learning/test_router.py`` does.
    """
    flattened = []
    for route in app.routes:
        nested = getattr(route, "original_router", None)
        if nested is None:
            if getattr(route, "path", "") == "/api/file-preview/pdf":
                flattened.append(SimpleNamespace(dependencies=list(route.dependant.dependencies)))
            continue
        ctx = getattr(route, "include_context", None)
        prefix = str(getattr(ctx, "prefix", "") or "")
        router_deps = list(getattr(ctx, "dependencies", None) or [])
        for inner in nested.routes:
            if prefix + str(getattr(inner, "path", "")) != "/api/file-preview/pdf":
                continue
            deps = list(inner.dependant.dependencies) + router_deps
            flattened.append(SimpleNamespace(dependencies=deps))
    return flattened


@pytest.mark.parametrize("lazy", [False, True])
def test_file_preview_route_normalizer_keeps_auth_dependency(lazy: bool) -> None:
    from fastapi import Depends

    from deeptutor.api.routers.auth import require_auth

    eager_dependency = SimpleNamespace(call=require_auth)
    if lazy:
        inner = SimpleNamespace(path="/pdf", dependant=SimpleNamespace(dependencies=[]))
        route = SimpleNamespace(
            original_router=SimpleNamespace(routes=[inner]),
            include_context=SimpleNamespace(
                prefix="/api/file-preview", dependencies=[Depends(require_auth)]
            ),
        )
    else:
        route = SimpleNamespace(
            path="/api/file-preview/pdf",
            dependant=SimpleNamespace(dependencies=[eager_dependency]),
        )

    normalized = _file_preview_routes(SimpleNamespace(routes=[route]))
    assert len(normalized) == 1
    assert any(
        (getattr(dependency, "call", None) or getattr(dependency, "dependency", None))
        is require_auth
        for dependency in normalized[0].dependencies
    )


def test_preview_route_requires_authentication(monkeypatch) -> None:
    from deeptutor.api.main import app
    from deeptutor.api.routers import auth

    routes = _file_preview_routes(app)
    assert len(routes) == 2  # GET source and POST uploaded bytes

    def _dep_call(dependency):
        # Route-level deps are Dependant objects (.call); router-level deps
        # coming from include_context are raw Depends (.dependency).
        return getattr(dependency, "call", None) or getattr(dependency, "dependency", None)

    assert all(
        any(_dep_call(dependency) is auth.require_auth for dependency in route.dependencies)
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


def test_powerpoint_preview_resolves_missing_fonts_and_refreshes_cache(
    monkeypatch, tmp_path: Path
) -> None:
    from pptx import Presentation
    from pptx.oxml.ns import qn
    from pptx.oxml.xmlchemy import OxmlElement
    from pptx.util import Inches

    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(6), Inches(1))
    for text, family in (("今天讲五件事 · OpenAI", "Microsoft YaHei"), ("日本語", "Yu Gothic")):
        run = box.text_frame.paragraphs[0].add_run()
        run.text = text
        run.font.name = "Arial"
        east_asian = OxmlElement("a:ea")
        east_asian.set("typeface", family)
        run._r.get_or_add_rPr().append(east_asian)
    data = BytesIO()
    deck.save(data)
    source = data.getvalue()

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    old_key = hashlib.sha256(b"office-preview-v1\0.pptx\0" + source).hexdigest()
    (cache_dir / f"{old_key}.pdf").write_bytes(b"%PDF-1.7\nold preview")
    calls: list[tuple[str, str]] = []
    families = {"pingfang sc"}
    monkeypatch.setattr(pptx_fonts, "_installed_families", lambda: families)
    monkeypatch.setattr(office_preview.shutil, "which", lambda _name: "/fake/soffice")
    monkeypatch.setattr(pptx_fonts, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.delenv("FONTCONFIG_FILE", raising=False)
    monkeypatch.setattr(pptx_fonts, "_MACOS_FONT_ASSETS", tmp_path)
    asset = tmp_path / "com_apple_MobileAsset_Font8" / "test.asset" / "AssetData"
    asset.mkdir(parents=True)
    (asset / "PingFang.ttc").touch()
    mapping = json.dumps(pptx_fonts.chinese_font_substitutions(), sort_keys=True).encode()
    old_key = hashlib.sha256(b"office-preview-v2\0.pptx\0" + mapping + b"\0" + source).hexdigest()
    (cache_dir / f"{old_key}.pdf").write_bytes(b"%PDF-1.7\nold headless preview")

    def fake_popen(args: list[str], *, env: dict[str, str], **_kwargs) -> SimpleNamespace:
        fontconfig = Path(env["FONTCONFIG_FILE"])
        assert fontconfig.parent == Path(env["FONTCONFIG_PATH"])
        config = fontconfig.read_text(encoding="utf-8")
        assert "<dir>/System/Library/Fonts</dir>" in config
        assert f"<dir>{asset}</dir>" in config
        path = Path(args[-1])
        runs = Presentation(path).slides[0].shapes[0].text_frame.paragraphs[0].runs
        assert [run.text for run in runs] == ["今天讲五件事 · OpenAI", "日本語"]
        assert runs[0].font.name == "Arial"
        fonts = tuple(run._r.find(f"{qn('a:rPr')}/{qn('a:ea')}").get("typeface") for run in runs)
        calls.append(fonts)
        output = Path(args[args.index("--outdir") + 1]) / path.with_suffix(".pdf").name
        output.write_bytes(b"%PDF-1.7\n" + fonts[0].encode())
        return SimpleNamespace(returncode=0, communicate=lambda **_kwargs: (b"", b""))

    monkeypatch.setattr(office_preview.subprocess, "Popen", fake_popen)

    def render() -> bytes:
        return asyncio.run(office_preview.render_office_pdf(source, "slides.pptx", cache_dir))

    assert render() == render() == b"%PDF-1.7\nPingFang SC"
    families.add("microsoft yahei")
    assert render() == b"%PDF-1.7\nMicrosoft YaHei"
    assert calls == [("PingFang SC", "Yu Gothic"), ("Microsoft YaHei", "Yu Gothic")]

    with ZipFile(BytesIO(source)) as original:
        assert b'typeface="Microsoft YaHei"' in original.read("ppt/slides/slide1.xml")


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
