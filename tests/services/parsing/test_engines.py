from __future__ import annotations

import builtins
from pathlib import Path
import subprocess
import zipfile

import httpx
import pytest

from deeptutor.services.parsing.engines import factory
from deeptutor.services.parsing.engines.docling.config import DoclingConfig
from deeptutor.services.parsing.engines.tika.config import TikaConfig
from deeptutor.services.parsing.types import ParserError


def test_known_engines() -> None:
    assert factory.KNOWN_ENGINES == {
        "text_only",
        "mineru",
        "docling",
        "markitdown",
        "pymupdf4llm",
        "liteparse",
        "tika",
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
        "tika",
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
    assert engines["tika"]["available"] is True
    assert engines["tika"]["needs_local_models"] is False


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


def test_mineru_advertises_current_document_and_image_formats() -> None:
    parser = factory.get_parser("mineru")
    from deeptutor.services.parsing.engines.mineru.formats import (
        MIN_MINERU_VERSION,
        mineru_version_is_current,
    )

    assert parser.supported_formats() == {
        ".pdf",
        ".png",
        ".jpeg",
        ".jpg",
        ".jp2",
        ".webp",
        ".gif",
        ".bmp",
        ".tiff",
        ".docx",
        ".pptx",
        ".xlsx",
    }
    assert MIN_MINERU_VERSION == "3.4.5"
    assert mineru_version_is_current("mineru, version 3.4.5") is True
    assert mineru_version_is_current("MinerU 3.5.0") is True
    assert mineru_version_is_current("magic-pdf, version 1.3.12") is False


def test_markitdown_advertises_all_current_builtin_formats() -> None:
    from deeptutor.services.parsing.engines.markitdown.formats import (
        MARKITDOWN_0_1_7_FORMATS,
        MIN_MARKITDOWN_VERSION,
        markitdown_supported_formats,
        markitdown_version_is_current,
    )

    assert MIN_MARKITDOWN_VERSION == "0.1.7"
    assert len(MARKITDOWN_0_1_7_FORMATS) == 28
    assert MARKITDOWN_0_1_7_FORMATS <= markitdown_supported_formats()
    assert {".pdf", ".docx", ".xls", ".msg", ".ipynb", ".zip"} <= (
        factory.get_parser("markitdown").supported_formats()
    )
    assert markitdown_version_is_current("0.1.7") is True
    assert markitdown_version_is_current("0.2.0") is True
    assert markitdown_version_is_current("0.1.6") is False


def test_markitdown_readiness_requires_current_package(monkeypatch) -> None:
    from deeptutor.services.parsing.engines.markitdown import engine as markitdown_engine

    parser = factory.get_parser("markitdown")
    monkeypatch.setattr(parser, "is_available", lambda: True)
    monkeypatch.setattr(markitdown_engine, "installed_markitdown_version", lambda: "0.1.6")

    report = parser.is_ready(parser.resolve_config())

    assert report.ready is False
    assert report.reason == "update_required"
    assert "0.1.7" in report.message


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


def test_docling_advertises_complete_current_upstream_formats() -> None:
    from deeptutor.services.parsing.engines.docling.formats import (
        DOCLING_2_123_1_FORMATS,
        MIN_DOCLING_VERSION,
        docling_supported_formats,
        docling_version_is_current,
    )

    assert MIN_DOCLING_VERSION == "2.123.1"
    assert len(DOCLING_2_123_1_FORMATS) == 74
    assert DOCLING_2_123_1_FORMATS <= docling_supported_formats()
    assert {
        ".pdf",
        ".doc",
        ".odt",
        ".pages",
        ".epub",
        ".eml",
        ".wav",
        ".mp4",
        ".dclg.xml",
        ".tar.gz",
    } <= factory.get_parser("docling").supported_formats()
    assert docling_version_is_current("2.123.1") is True
    assert docling_version_is_current("2.124.0") is True
    assert docling_version_is_current("2.122.9") is False


def test_docling_format_discovery_never_imports_the_runtime(monkeypatch) -> None:
    from deeptutor.services.parsing.engines.docling.formats import (
        DOCLING_2_123_1_FORMATS,
        docling_supported_formats,
    )

    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "docling" or name.startswith("docling."):
            raise AssertionError("format discovery must not import Docling/PyTorch")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    assert docling_supported_formats() == DOCLING_2_123_1_FORMATS


def test_docling_remote_readiness_needs_no_local_package() -> None:
    parser = factory.get_parser("docling")
    from deeptutor.services.parsing.engines.docling.config import DoclingConfig

    # Remote mode is ready with a URL set — even if the docling package is absent.
    assert parser.is_ready(DoclingConfig(mode="remote", api_base_url="http://host:5001")).ready
    blocked = parser.is_ready(DoclingConfig(mode="remote", api_base_url=""))
    assert blocked.ready is False
    assert blocked.reason == "not_configured"


def test_docling_local_readiness_requires_current_package(monkeypatch) -> None:
    from deeptutor.services.parsing.engines.docling import engine as docling_engine

    parser = factory.get_parser("docling")
    monkeypatch.setattr(parser, "is_available", lambda: True)
    monkeypatch.setattr(docling_engine, "installed_docling_version", lambda: "2.122.0")

    report = parser.is_ready(DoclingConfig(mode="local"))

    assert report.ready is False
    assert report.reason == "update_required"
    assert "2.123.1" in report.message


def test_docling_local_parse_runs_in_isolated_worker(tmp_path, monkeypatch) -> None:
    from deeptutor.services.parsing.engines.docling import local_worker

    source = tmp_path / "lesson.pdf"
    source.write_bytes(b"%PDF-1.4 fake")
    workdir = tmp_path / "parsed"
    workdir.mkdir()
    captured: dict = {}

    class _FakeProcess:
        stdout = iter(["worker ready\n", "converted\n"])

        def wait(self, timeout=None):
            captured.setdefault("wait_timeouts", []).append(timeout)
            return 0

        def poll(self):
            return 0

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return _FakeProcess()

    monkeypatch.setattr(local_worker.subprocess, "Popen", fake_popen)
    output: list[str] = []

    local_worker.parse_local(
        source,
        workdir,
        config=DoclingConfig(mode="local", do_ocr=True, do_table_structure=False),
        on_output=output.append,
    )

    assert captured["command"][:3] == [
        local_worker.sys.executable,
        "-m",
        "deeptutor.services.parsing.engines.docling.local_worker",
    ]
    assert captured["command"][-1] == "--do-ocr"
    assert "--do-table-structure" not in captured["command"]
    assert captured["kwargs"]["stderr"] is subprocess.STDOUT
    assert captured["kwargs"]["env"]["PYTHONUNBUFFERED"] == "1"
    assert output == ["worker ready", "converted"]


def test_docling_local_worker_failure_is_actionable(tmp_path, monkeypatch) -> None:
    from deeptutor.services.parsing.engines.docling import local_worker

    source = tmp_path / "lesson.pdf"
    source.write_bytes(b"%PDF-1.4 fake")
    workdir = tmp_path / "parsed"
    workdir.mkdir()

    class _FailingProcess:
        stdout = iter(["model load failed\n"])

        def wait(self, timeout=None):
            return 7

        def poll(self):
            return 7

    monkeypatch.setattr(
        local_worker.subprocess, "Popen", lambda *_args, **_kwargs: _FailingProcess()
    )

    with pytest.raises(ParserError, match="code 7.*model load failed"):
        local_worker.parse_local(source, workdir, config=DoclingConfig(mode="local"))


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


def test_tika_signature_tracks_server_url() -> None:
    parser = factory.get_parser("tika")
    a = parser.signature(TikaConfig(server_url="http://host:9998")).hash()
    b = parser.signature(TikaConfig(server_url="http://other:9998")).hash()
    assert a != b


def test_tika_readiness_needs_url() -> None:
    parser = factory.get_parser("tika")
    assert parser.is_available() is True
    assert parser.is_ready(TikaConfig(server_url="http://host:9998")).ready
    blocked = parser.is_ready(TikaConfig(server_url=""))
    assert blocked.ready is False
    assert blocked.reason == "not_configured"


def test_tika_delegates_format_detection_and_tracks_current_server() -> None:
    from deeptutor.services.parsing.engines.tika.formats import (
        MIN_TIKA_VERSION,
        TIKA_4_0_0_KNOWN_FORMATS,
        tika_version_is_current,
    )

    # Empty is intentional: ParseService treats it as server-authoritative,
    # including custom parsers that DeepTutor cannot enumerate locally.
    assert factory.get_parser("tika").supported_formats() == frozenset()
    assert MIN_TIKA_VERSION == "4.0.0"
    assert len(TIKA_4_0_0_KNOWN_FORMATS) >= 175
    assert {".pdf", ".vsdx", ".pst", ".sqlite3", ".hwp", ".jxl"} <= (TIKA_4_0_0_KNOWN_FORMATS)
    assert tika_version_is_current("Apache Tika 4.0.0") is True
    assert tika_version_is_current("Apache Tika 4.1.0-SNAPSHOT") is True
    assert tika_version_is_current("Apache Tika 3.2.3") is False


@pytest.mark.parametrize(
    ("version", "expected_ok"),
    [("Apache Tika 4.0.0", True), ("Apache Tika 3.2.3", False)],
)
def test_tika_verify_enforces_current_server(
    monkeypatch: pytest.MonkeyPatch, version: str, expected_ok: bool
) -> None:
    from deeptutor.services.parsing.engines.tika import remote

    class _FakeClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(remote.httpx, "Client", _FakeClient)
    monkeypatch.setattr(remote, "_get_text", lambda *_args: version)

    ok, detail = remote.verify_remote(TikaConfig(server_url="http://host:9998"))

    assert ok is expected_ok
    assert version in detail
    if not expected_ok:
        assert "4.0.0" in detail


def test_tika_parse_writes_markdown(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-1.4 fake")
    workdir = tmp_path / "parsed"
    workdir.mkdir()

    captured: dict = {}

    class _FakeResponse:
        text = "# Extracted via Tika\n"

        def raise_for_status(self):
            return None

    class _FakeClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def put(self, endpoint, content=None, headers=None):
            captured["endpoint"] = endpoint
            captured["headers"] = headers
            return _FakeResponse()

    monkeypatch.setattr(httpx, "Client", _FakeClient)
    parser = factory.get_parser("tika")
    parser.parse(src, workdir, config=TikaConfig(server_url="http://host:9998"))

    assert captured["endpoint"] == "/tika"
    assert "Accept" not in captured["headers"]
    assert captured["headers"]["Content-Type"] == "application/octet-stream"
    assert "doc.pdf" in captured["headers"]["Content-Disposition"]
    assert (workdir / "doc.md").read_text(encoding="utf-8") == "# Extracted via Tika\n"


def test_tika_http_error_raises(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-1.4 fake")
    workdir = tmp_path / "parsed"
    workdir.mkdir()

    class _FailingResponse:
        status_code = 422

        def raise_for_status(self):
            request = httpx.Request("PUT", "http://host:9998/tika")
            response = httpx.Response(422, request=request)
            raise httpx.HTTPStatusError("unprocessable", request=request, response=response)

    class _FailingClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def put(self, *args, **kwargs):
            return _FailingResponse()

    monkeypatch.setattr(httpx, "Client", _FailingClient)
    parser = factory.get_parser("tika")
    with pytest.raises(ParserError, match="422"):
        parser.parse(src, workdir, config=TikaConfig(server_url="http://host:9998"))
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


def test_pymupdf4llm_advertises_current_pymupdf_formats() -> None:
    from deeptutor.services.parsing.engines.pymupdf4llm.formats import (
        MIN_PYMUPDF4LLM_VERSION,
        PYMUPDF4LLM_1_28_2_FORMATS,
        pymupdf4llm_version_is_current,
    )

    assert MIN_PYMUPDF4LLM_VERSION == "1.28.2"
    assert len(PYMUPDF4LLM_1_28_2_FORMATS) == 28
    assert {".pdf", ".xps", ".epub", ".mobi", ".cbz", ".svg", ".jxr", ".psd"} <= (
        factory.get_parser("pymupdf4llm").supported_formats()
    )
    assert ".docx" not in PYMUPDF4LLM_1_28_2_FORMATS
    assert pymupdf4llm_version_is_current("1.28.2") is True
    assert pymupdf4llm_version_is_current("1.29.0") is True
    assert pymupdf4llm_version_is_current("0.3.4") is False


def test_pymupdf4llm_readiness_reflects_install() -> None:
    from deeptutor.services.parsing.engines.pymupdf4llm.formats import (
        installed_pymupdf4llm_version,
        pymupdf4llm_version_is_current,
    )

    parser = factory.get_parser("pymupdf4llm")
    # Name lookup is case-insensitive (the metadata label is mixed-case).
    assert type(factory.get_parser("PyMuPDF4LLM")) is type(parser)
    report = parser.is_ready(parser.resolve_config())
    if parser.is_available():
        if pymupdf4llm_version_is_current(installed_pymupdf4llm_version()):
            assert report.ready is True
        else:
            assert report.reason == "update_required"
    else:
        # Absent optional package → gated with a pip-install hint, not a crash.
        assert report.reason == "not_configured"
        assert "pymupdf4llm" in report.message


def test_pymupdf4llm_readiness_requires_current_package(monkeypatch) -> None:
    from deeptutor.services.parsing.engines.pymupdf4llm import engine as pymupdf_engine

    parser = factory.get_parser("pymupdf4llm")
    monkeypatch.setattr(parser, "is_available", lambda: True)
    monkeypatch.setattr(pymupdf_engine, "installed_pymupdf4llm_version", lambda: "0.3.4")

    report = parser.is_ready(parser.resolve_config())

    assert report.ready is False
    assert report.reason == "update_required"
    assert "1.28.2" in report.message


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


def test_liteparse_advertises_all_current_input_formats() -> None:
    from deeptutor.services.parsing.engines.liteparse.formats import (
        LITEPARSE_2_14_2_FORMATS,
        MIN_LITEPARSE_VERSION,
        liteparse_version_is_current,
    )

    assert MIN_LITEPARSE_VERSION == "2.14.2"
    assert len(LITEPARSE_2_14_2_FORMATS) == 27
    assert {".pdf", ".docm", ".pages", ".key", ".numbers", ".ods", ".svg"} <= (
        factory.get_parser("liteparse").supported_formats()
    )
    assert liteparse_version_is_current("2.14.2") is True
    assert liteparse_version_is_current("2.15.0") is True
    assert liteparse_version_is_current("2.14.1") is False


def test_liteparse_readiness_reflects_install() -> None:
    from deeptutor.services.parsing.engines.liteparse.formats import (
        installed_liteparse_version,
        liteparse_version_is_current,
    )

    parser = factory.get_parser("liteparse")
    # Name lookup is case-insensitive (the metadata label is mixed-case).
    assert type(factory.get_parser("LiteParse")) is type(parser)
    report = parser.is_ready(parser.resolve_config())
    if parser.is_available():
        if liteparse_version_is_current(installed_liteparse_version()):
            assert report.ready is True
        else:
            assert report.reason == "update_required"
    else:
        assert report.reason == "not_configured"
        assert "liteparse" in report.message


def test_liteparse_readiness_requires_current_package(monkeypatch) -> None:
    from deeptutor.services.parsing.engines.liteparse import engine as liteparse_engine

    parser = factory.get_parser("liteparse")
    monkeypatch.setattr(parser, "is_available", lambda: True)
    monkeypatch.setattr(liteparse_engine, "installed_liteparse_version", lambda: "2.14.1")

    report = parser.is_ready(parser.resolve_config())

    assert report.ready is False
    assert report.reason == "update_required"
    assert "2.14.2" in report.message


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
    assert ENGINE_PIP_SPECS["markitdown"] == ["markitdown[all]>=0.1.7"]
    assert ENGINE_PIP_SPECS["pymupdf4llm"] == ["pymupdf4llm>=1.28.2"]
    assert ENGINE_PIP_SPECS["liteparse"] == ["liteparse>=2.14.2"]
    assert ENGINE_PIP_SPECS["docling"] == [
        "docling[xbrl]>=2.123.1",
        "docling-slim[format-iwork,format-opendocument,format-video]>=2.123.1",
    ]
    assert "text_only" not in ENGINE_PIP_SPECS
    assert "mineru" not in ENGINE_PIP_SPECS


def test_install_manager_upgrades_existing_package(monkeypatch) -> None:
    from deeptutor.services.parsing.engines import _install

    manager = _install.BackgroundJobManager()
    captured: dict = {}

    def fake_launch(**kwargs):
        captured.update(kwargs)
        return {"ok": True, "message": ""}

    monkeypatch.setattr(manager, "_launch", fake_launch)
    manager.start_install(engine="docling", specs=_install.ENGINE_PIP_SPECS["docling"])

    assert captured["cmd"][:6] == [
        _install.sys.executable,
        "-m",
        "pip",
        "install",
        "--upgrade",
        "--no-input",
    ]


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


def test_resolve_model_downloader_finds_windows_exe_next_to_python(monkeypatch, tmp_path) -> None:
    from deeptutor.services.parsing.engines import _install

    scripts_dir = tmp_path / "Scripts"
    scripts_dir.mkdir()
    python_exe = scripts_dir / "python.exe"
    downloader_exe = scripts_dir / "docling-tools.exe"
    calls: list[tuple[str, str | None]] = []

    def fake_which(command: str, *, path: str | None = None) -> str | None:
        calls.append((command, path))
        if path == str(scripts_dir):
            # On Windows shutil.which applies PATHEXT and resolves this .exe.
            return str(downloader_exe)
        return None

    monkeypatch.setattr(_install.sys, "executable", str(python_exe))
    monkeypatch.setattr(_install.shutil, "which", fake_which)

    assert _install.resolve_model_downloader("docling") == [
        str(downloader_exe),
        "models",
        "download",
    ]
    assert calls == [("docling-tools", str(scripts_dir))]


def test_resolve_model_downloader_falls_back_to_path(monkeypatch, tmp_path) -> None:
    from deeptutor.services.parsing.engines import _install

    scripts_dir = tmp_path / "Scripts"
    path_downloader = tmp_path / "bin" / "docling-tools"
    calls: list[tuple[str, str | None]] = []

    def fake_which(command: str, *, path: str | None = None) -> str | None:
        calls.append((command, path))
        return str(path_downloader) if path is None else None

    monkeypatch.setattr(_install.sys, "executable", str(scripts_dir / "python.exe"))
    monkeypatch.setattr(_install.shutil, "which", fake_which)

    assert _install.resolve_model_downloader("docling") == [
        str(path_downloader),
        "models",
        "download",
    ]
    assert calls == [
        ("docling-tools", str(scripts_dir)),
        ("docling-tools", None),
    ]


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
