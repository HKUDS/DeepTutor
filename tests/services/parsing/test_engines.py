from __future__ import annotations

from pathlib import Path
import zipfile

import httpx
import pytest

from deeptutor.services.parsing.engines import factory
from deeptutor.services.parsing.engines.docling.config import DoclingConfig
from deeptutor.services.parsing.types import ParserError


def test_known_engines() -> None:
    assert factory.KNOWN_ENGINES == {
        "text_only",
        "mineru",
        "docling",
        "markitdown",
        "pymupdf4llm",
        "liteparse",
    }


def test_list_engines_reports_metadata_and_availability() -> None:
    engines = {entry["id"]: entry for entry in factory.list_engines()}
    assert set(engines) == {
        "text_only",
        "mineru",
        "docling",
        "markitdown",
        "pymupdf4llm",
        "liteparse",
    }
    assert engines["text_only"]["available"] is True
    assert engines["text_only"]["needs_local_models"] is False
    # MinerU is an external CLI / hosted API — the adapter is always available;
    # readiness (not availability) gates actual use.
    assert engines["mineru"]["available"] is True
    assert engines["mineru"]["needs_local_models"] is True
    assert engines["markitdown"]["needs_local_models"] is False
    assert engines["pymupdf4llm"]["needs_local_models"] is False
    assert engines["liteparse"]["needs_local_models"] is False


def test_get_parser_unknown_raises() -> None:
    with pytest.raises(ParserError):
        factory.get_parser("nope")


def test_text_only_parser_extracts_docx_text(tmp_path) -> None:
    parser = factory.get_parser("text_only")
    assert type(factory.get_parser("text-only")) is type(parser)
    docx = tmp_path / "lesson.docx"
    with zipfile.ZipFile(docx, "w") as zf:
        zf.writestr(
            "word/document.xml",
            """
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body>
                <w:p><w:r><w:t>Hello DeepTutor</w:t></w:r></w:p>
              </w:body>
            </w:document>
            """.strip(),
        )

    workdir = tmp_path / "parsed"
    workdir.mkdir()
    parser.parse(docx, workdir, config={})

    assert (workdir / "lesson.md").read_text(encoding="utf-8") == "Hello DeepTutor"


def test_mineru_signature_distinguishes_local_and_cloud() -> None:
    parser = factory.get_parser("mineru")
    from deeptutor.services.parsing.engines.mineru.config import MinerUConfig

    local = parser.signature(MinerUConfig(mode="local")).hash()
    cloud = parser.signature(MinerUConfig(mode="cloud")).hash()
    assert local != cloud


def test_mineru_cloud_readiness_needs_token() -> None:
    from deeptutor.services.parsing.engines.mineru.config import MinerUConfig
    from deeptutor.services.parsing.engines.mineru.readiness import mineru_readiness

    assert mineru_readiness(MinerUConfig(mode="cloud", api_token="")).reason == "not_configured"
    assert mineru_readiness(MinerUConfig(mode="cloud", api_token="tok")).ready is True


def test_docling_signature_distinguishes_local_and_remote() -> None:
    parser = factory.get_parser("docling")
    from deeptutor.services.parsing.engines.docling.config import DoclingConfig

    local = parser.signature(DoclingConfig(mode="local")).hash()
    remote = parser.signature(DoclingConfig(mode="remote", api_base_url="http://host:5001")).hash()
    other_host = parser.signature(
        DoclingConfig(mode="remote", api_base_url="http://other:5001")
    ).hash()
    assert local != remote
    assert remote != other_host


def test_docling_remote_readiness_needs_no_local_package() -> None:
    parser = factory.get_parser("docling")
    from deeptutor.services.parsing.engines.docling.config import DoclingConfig

    # Remote mode is ready with a URL set — even if the docling package is absent.
    assert parser.is_ready(DoclingConfig(mode="remote", api_base_url="http://host:5001")).ready
    blocked = parser.is_ready(DoclingConfig(mode="remote", api_base_url=""))
    assert blocked.ready is False
    assert blocked.reason == "not_configured"


def test_docling_remote_parse_writes_markdown(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    workdir = tmp_path / "parsed"
    workdir.mkdir()

    captured: dict = {}

    class _FakeClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def post(self, endpoint, files=None, data=None):
            captured["endpoint"] = endpoint
            captured["files"] = files
            captured["data"] = data
            return _FakeResponse(
                {
                    "status": "success",
                    "document": {"md_content": "# Extracted via Docling serve\n"},
                }
            )

    class _FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    monkeypatch.setattr(httpx, "Client", _FakeClient)
    parser = factory.get_parser("docling")
    parser.parse(pdf, workdir, config=DoclingConfig(mode="remote", api_base_url="http://host:5001"))

    # Remote parse goes to /v1/convert/file with markdown output requested and
    # the parsed markdown written to <stem>.md.
    assert captured["endpoint"] == "/v1/convert/file"
    assert captured["data"]["to_formats"] == "md"
    assert captured["files"]["files"][1].closed
    assert (workdir / "doc.md").read_text(encoding="utf-8") == "# Extracted via Docling serve\n"


def test_docling_remote_business_error_raises(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    workdir = tmp_path / "parsed"
    workdir.mkdir()

    class _FailingResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"status": "failure", "errors": [{"error": "bad file"}], "document": None}

    class _FailingClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def post(self, *args, **kwargs):
            return _FailingResponse()

    monkeypatch.setattr(httpx, "Client", _FailingClient)
    parser = factory.get_parser("docling")
    with pytest.raises(ParserError, match="bad file"):
        parser.parse(
            pdf, workdir, config=DoclingConfig(mode="remote", api_base_url="http://host:5001")
        )
    assert not (workdir / "doc.md").exists()


def test_mineru_local_model_download_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    from deeptutor.services.parsing.engines.mineru import backend
    from deeptutor.services.parsing.engines.mineru import readiness as rd
    from deeptutor.services.parsing.engines.mineru.config import MinerUConfig

    monkeypatch.setattr(
        backend,
        "local_cli_probe",
        lambda p="": {"found": True, "command": "mineru", "path": "", "source": "path"},
    )
    monkeypatch.setattr(rd, "mineru_models_ready", lambda source="huggingface": False)

    # Models missing + auto-download off → gated.
    blocked = rd.mineru_readiness(MinerUConfig(mode="local", allow_local_model_download=False))
    assert blocked.ready is False
    assert blocked.reason == "models_missing"

    # Explicit opt-in → allowed.
    allowed = rd.mineru_readiness(MinerUConfig(mode="local", allow_local_model_download=True))
    assert allowed.ready is True

    # CLI missing → distinct gate.
    monkeypatch.setattr(
        backend,
        "local_cli_probe",
        lambda p="": {"found": False, "command": "", "path": "", "source": "path"},
    )
    no_cli = rd.mineru_readiness(MinerUConfig(mode="local"))
    assert no_cli.reason == "cli_missing"


def test_pymupdf4llm_signature_tracks_image_knobs() -> None:
    parser = factory.get_parser("pymupdf4llm")
    from deeptutor.services.parsing.engines.pymupdf4llm.config import PyMuPDF4LLMConfig

    base = parser.signature(
        PyMuPDF4LLMConfig(write_images=True, image_format="png", image_dpi=150)
    ).hash()
    other_dpi = parser.signature(
        PyMuPDF4LLMConfig(write_images=True, image_format="png", image_dpi=300)
    ).hash()
    no_images = parser.signature(PyMuPDF4LLMConfig(write_images=False)).hash()
    assert base != other_dpi
    assert base != no_images


def test_pymupdf4llm_readiness_reflects_install() -> None:
    parser = factory.get_parser("pymupdf4llm")
    # Name lookup is case-insensitive (the metadata label is mixed-case).
    assert type(factory.get_parser("PyMuPDF4LLM")) is type(parser)
    report = parser.is_ready(parser.resolve_config())
    if parser.is_available():
        assert report.ready is True
    else:
        # Absent optional package → gated with a pip-install hint, not a crash.
        assert report.reason == "not_configured"
        assert "pymupdf4llm" in report.message


def test_pymupdf4llm_parses_pdf_and_extracts_images(tmp_path) -> None:
    pymupdf = pytest.importorskip("pymupdf")
    pytest.importorskip("pymupdf4llm")
    from deeptutor.services.parsing.engines.pymupdf4llm.config import PyMuPDF4LLMConfig

    pdf = tmp_path / "doc.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Hello DeepTutor via PyMuPDF4LLM")
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 120, 120))
    pix.clear_with(128)
    page.insert_image(pymupdf.Rect(100, 200, 320, 420), pixmap=pix)
    doc.save(pdf)
    doc.close()

    parser = factory.get_parser("pymupdf4llm")
    workdir = tmp_path / "parsed"
    workdir.mkdir()
    parser.parse(
        pdf,
        workdir,
        config=PyMuPDF4LLMConfig(write_images=True, image_format="png", image_dpi=96),
    )

    md = (workdir / "doc.md").read_text(encoding="utf-8")
    assert "DeepTutor" in md
    images = workdir / "images"
    assert images.is_dir()
    extracted = list(images.glob("*.png"))
    assert extracted, "expected at least one extracted image"
    # Links are rewritten to the portable images/<name> form, not an abs path.
    assert any(f"images/{p.name}" in md for p in extracted)
    assert str(images) not in md


def test_pymupdf4llm_no_images_leaves_no_asset_dir(tmp_path) -> None:
    pymupdf = pytest.importorskip("pymupdf")
    pytest.importorskip("pymupdf4llm")
    from deeptutor.services.parsing.engines.pymupdf4llm.config import PyMuPDF4LLMConfig

    pdf = tmp_path / "text.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Text only, no figures here.")
    doc.save(pdf)
    doc.close()

    parser = factory.get_parser("pymupdf4llm")
    workdir = tmp_path / "parsed"
    workdir.mkdir()
    parser.parse(pdf, workdir, config=PyMuPDF4LLMConfig(write_images=True))

    assert (workdir / "text.md").exists()
    # An empty images/ dir is cleaned up so the cache loader sees no asset_dir.
    assert not (workdir / "images").exists()


def test_liteparse_signature_tracks_knobs() -> None:
    parser = factory.get_parser("liteparse")
    from deeptutor.services.parsing.engines.liteparse.config import LiteParseConfig

    base = parser.signature(LiteParseConfig()).hash()
    with_images = parser.signature(LiteParseConfig(extract_images=True)).hash()
    capped = parser.signature(LiteParseConfig(max_pages=5)).hash()
    assert base != with_images
    assert base != capped


def test_liteparse_readiness_reflects_install() -> None:
    parser = factory.get_parser("liteparse")
    # Name lookup is case-insensitive (the metadata label is mixed-case).
    assert type(factory.get_parser("LiteParse")) is type(parser)
    report = parser.is_ready(parser.resolve_config())
    if parser.is_available():
        assert report.ready is True
    else:
        assert report.reason == "not_configured"
        assert "liteparse" in report.message


def test_liteparse_config_rejects_unknown_image_mode_and_coerces_strings() -> None:
    from deeptutor.services.config.runtime_settings import RuntimeSettingsService

    normalized = RuntimeSettingsService._normalize_liteparse_engine(
        None,  # type: ignore[arg-type] - pure function of its argument
        {
            "image_mode": "IMAGINARY",
            # Settings round-trip through JSON/env can deliver strings; a bare
            # bool() would read "false" as True.
            "extract_links": "false",
            "extract_images": "true",
            "max_pages": "-3",
        },
    )
    assert normalized == {
        "image_mode": "placeholder",
        "extract_links": False,
        "extract_images": True,
        "max_pages": 0,
    }


def _install_fake_liteparse(monkeypatch, *, image_names: tuple[str, ...] = ()) -> dict:
    """Stand in for the compiled ``liteparse`` package, recording its kwargs."""
    import sys
    import types

    seen: dict = {}

    class _FakeImage:
        def __init__(self, name: str) -> None:
            self.name = name

    class _FakeResult:
        def __init__(self, text: str, images: list) -> None:
            self.text = text
            self.images = images

    class _FakeLiteParse:
        def __init__(self, **kwargs) -> None:
            seen["kwargs"] = kwargs

        def parse(self, path: str):
            seen["path"] = path
            body = " ".join(f"![]({name})" for name in image_names)
            out_dir = seen["kwargs"].get("image_output_dir")
            if out_dir:
                for name in image_names:
                    (Path(out_dir) / name).write_bytes(b"\x89PNG")
            return _FakeResult(f"# Doc\n\n{body}\n", [_FakeImage(n) for n in image_names])

    module = types.ModuleType("liteparse")
    module.LiteParse = _FakeLiteParse  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "liteparse", module)
    return seen


def test_liteparse_pins_markdown_output_and_images_dir(tmp_path, monkeypatch) -> None:
    """The workdir contract, not the library's defaults, decides these two."""
    from deeptutor.services.parsing.engines.liteparse.config import LiteParseConfig

    seen = _install_fake_liteparse(monkeypatch, image_names=("img_p1_1.png",))
    workdir = tmp_path / "work"
    workdir.mkdir()
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"%PDF-1.4")

    factory.get_parser("liteparse").parse(
        source, workdir, config=LiteParseConfig(extract_images=True, max_pages=7)
    )

    # LiteParse defaults output_format to "json"; a .md holding JSON would be
    # a mislabelled document, so the engine pins Markdown.
    assert seen["kwargs"]["output_format"] == "markdown"
    assert seen["kwargs"]["image_output_dir"] == str(workdir / "images")
    assert seen["kwargs"]["max_pages"] == 7
    # A systemic OCR failure must degrade, not lose the whole document.
    assert seen["kwargs"]["ocr_failure_fatal"] is False

    markdown = (workdir / "paper.md").read_text(encoding="utf-8")
    # Bare ``![](img_p1_1.png)`` is invalid once the file lands in images/.
    assert "![](images/img_p1_1.png)" in markdown
    assert (workdir / "images" / "img_p1_1.png").exists()


def test_liteparse_without_images_leaves_no_asset_dir(tmp_path, monkeypatch) -> None:
    from deeptutor.services.parsing.engines.liteparse.config import LiteParseConfig

    seen = _install_fake_liteparse(monkeypatch)
    workdir = tmp_path / "work"
    workdir.mkdir()
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"%PDF-1.4")

    factory.get_parser("liteparse").parse(
        source, workdir, config=LiteParseConfig(extract_images=False)
    )

    assert "extract_images" not in seen["kwargs"]
    assert "image_output_dir" not in seen["kwargs"]
    # An empty asset dir would make the cache loader report assets that
    # aren't there.
    assert not (workdir / "images").exists()


def test_liteparse_leaves_foreign_image_links_alone(tmp_path, monkeypatch) -> None:
    """Only names LiteParse reports as extracted get the images/ prefix."""
    from deeptutor.services.parsing.engines.liteparse.engine import LiteParseParser

    rewritten = LiteParseParser._portable_image_links(
        "![a](img_p1_1.png) ![b](https://example.com/logo.png)",
        [type("I", (), {"name": "img_p1_1.png"})()],
    )
    assert "![a](images/img_p1_1.png)" in rewritten
    assert "![b](https://example.com/logo.png)" in rewritten


def test_install_manager_spec_allowlist() -> None:
    from deeptutor.services.parsing.engines._install import (
        ENGINE_PIP_SPECS,
        installable_engines,
    )

    # Only optional pip-backed engines are installable; built-in / external are not.
    assert installable_engines() == {"pymupdf4llm", "markitdown", "docling", "liteparse"}
    assert ENGINE_PIP_SPECS["pymupdf4llm"] == ["pymupdf4llm>=0.0.17,<1.0"]
    assert ENGINE_PIP_SPECS["liteparse"] == ["liteparse>=2.11.1,<3.0"]
    assert "text_only" not in ENGINE_PIP_SPECS
    assert "mineru" not in ENGINE_PIP_SPECS


def test_model_download_allowlist() -> None:
    from deeptutor.services.parsing.engines._install import (
        ENGINE_MODEL_DOWNLOADERS,
        model_downloadable_engines,
    )

    # Only Docling fetches model weights; the others need no models.
    assert model_downloadable_engines() == {"docling"}
    assert ENGINE_MODEL_DOWNLOADERS["docling"][0] == "docling-tools"
    assert "pymupdf4llm" not in ENGINE_MODEL_DOWNLOADERS
    assert "liteparse" not in ENGINE_MODEL_DOWNLOADERS


def test_resolve_model_downloader_unknown_engine() -> None:
    from deeptutor.services.parsing.engines._install import resolve_model_downloader

    assert resolve_model_downloader("pymupdf4llm") is None
    assert resolve_model_downloader("nope") is None


def test_background_job_manager_idle_status() -> None:
    from deeptutor.services.parsing.engines._install import get_background_job_manager

    status = get_background_job_manager().status(0)
    assert status["state"] in {"idle", "running", "done", "failed", "cancelled"}
    assert status["kind"] in {"", "install", "models"}
    assert "engine" in status
    assert isinstance(status["lines"], list)


def test_docling_models_dir_honors_cache_env(monkeypatch, tmp_path) -> None:
    from deeptutor.services.parsing.engines.docling import engine as docling_engine

    monkeypatch.setenv("DOCLING_CACHE_DIR", str(tmp_path))
    assert docling_engine.docling_models_dir() == tmp_path / "models"
    # Empty cache → not ready; a populated models dir → detected as ready.
    monkeypatch.delenv("DOCLING_ARTIFACTS_PATH", raising=False)
    monkeypatch.setenv("HF_HOME", str(tmp_path / "nohub"))
    assert docling_engine._docling_models_ready() is False
    models = tmp_path / "models" / "layout"
    models.mkdir(parents=True)
    (models / "model.bin").write_bytes(b"x")
    assert docling_engine._docling_models_ready() is True
