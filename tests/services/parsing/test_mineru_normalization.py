"""Synthetic PDFs only; no cloud transport or production settings."""

from dataclasses import replace
import io

from PIL import Image
import pytest

pymupdf = pytest.importorskip("pymupdf")

from deeptutor.services.parsing.engines.mineru import normalization
from deeptutor.services.parsing.engines.mineru.config import MinerUConfig, MinerUError
from deeptutor.services.parsing.engines.mineru.engine import MinerUParser

CFG = MinerUConfig(mode="cloud", normalize_tiny_scans=True, language="en", model_version="vlm")


def scan(path, *, kind="tiny", alpha=False):
    data = io.BytesIO()
    image = Image.new(
        "RGBA" if alpha else "RGB", (1920, 2992), (255, 255, 255, 128) if alpha else "white"
    )
    image.save(data, format="PNG" if alpha else "JPEG")
    with pymupdf.open() as doc:
        for mode in ["tiny", "normal", "rotated"] if kind == "mixed" else [kind]:
            page = doc.new_page(
                width=492 if mode == "normal" else 41, height=768 if mode == "normal" else 64
            )
            page.insert_image(page.rect, stream=data.getvalue())
            if mode == "rotated":
                page.set_rotation(90)
            elif mode == "cropped":
                page.set_cropbox(pymupdf.Rect(1, 1, 40, 63))
            elif mode == "unit":
                doc.xref_set_key(page.xref, "UserUnit", "2")
            elif mode == "text":
                page.insert_text((2, 10), "text", fontsize=5)
            elif mode == "vector":
                page.draw_line((1, 1), (20, 20))
            elif mode == "annotated":
                page.add_text_annot((10, 10), "note")
        doc.save(path)
    return path


@pytest.mark.parametrize("alpha", [False, True])
def test_normalizes_copy_preserves_streams_source_and_parser_choices(tmp_path, alpha):
    source = scan(tmp_path / "scan.pdf", alpha=alpha)
    before = source.read_bytes()
    messages = []
    with normalization.working_copy(source, tmp_path / "out", CFG, messages.append) as copy:
        assert copy != source and copy.name == source.name
        assert normalization._image_streams(copy) == normalization._image_streams(source)
        with pymupdf.open(copy) as doc:
            assert doc[0].rect == pymupdf.Rect(0, 0, 492, 768)
        assert (CFG.language, CFG.model_version, CFG.is_ocr) == ("en", "vlm", False)
    assert source.read_bytes() == before
    assert not copy.exists()
    assert len(messages) == 1


@pytest.mark.parametrize(
    "kind", ["normal", "rotated", "cropped", "unit", "text", "vector", "annotated"]
)
def test_conservative_passthrough(tmp_path, kind):
    source = scan(tmp_path / "scan.pdf", kind=kind)
    before = source.read_bytes()
    with normalization.working_copy(source, tmp_path / "out", CFG) as copy:
        assert copy == source
    assert source.read_bytes() == before


@pytest.mark.parametrize(
    "config",
    [
        MinerUConfig(),
        replace(CFG, normalize_tiny_scans=False),
        replace(CFG, mode="local"),
        replace(CFG, api_base_url="https://example.test"),
    ],
)
def test_disabled_or_out_of_scope_does_not_inspect_pdf(tmp_path, config, monkeypatch):
    def fail(_):
        pytest.fail("must not inspect a disabled/out-of-scope input")

    monkeypatch.setattr(normalization, "_plan", fail)
    source = tmp_path / "scan.pdf"
    with normalization.working_copy(source, tmp_path / "out", config) as copy:
        assert copy == source


def test_mixed_pages_preserve_order_and_skip_complex_geometry(tmp_path):
    source = scan(tmp_path / "mixed.pdf", kind="mixed")
    with normalization.working_copy(source, tmp_path / "out", CFG) as copy:
        with pymupdf.open(copy) as doc:
            assert len(doc) == 3
            assert doc[0].rect == doc[1].rect == pymupdf.Rect(0, 0, 492, 768)
            assert doc[2].rotation == 90
            assert doc[2].rect == pymupdf.Rect(0, 0, 64, 41)


def test_cleanup_after_cloud_failure(tmp_path):
    source = scan(tmp_path / "scan.pdf")
    with (
        pytest.raises(RuntimeError),
        normalization.working_copy(source, tmp_path / "out", CFG) as copy,
    ):
        raise RuntimeError("cloud failed")
    assert not copy.exists()
    assert not list(tmp_path.glob(".mineru-normalized-*"))


def test_rejects_changed_streams(tmp_path, monkeypatch):
    source = scan(tmp_path / "scan.pdf")
    monkeypatch.setattr(normalization, "_image_streams", lambda path: [[str(path)]])
    with (
        pytest.raises(MinerUError, match="changed image streams"),
        normalization.working_copy(source, tmp_path / "out", CFG),
    ):
        pytest.fail("must not upload a modified image stream")
    assert not list(tmp_path.glob(".mineru-normalized-*"))


def test_signature_is_opt_in_and_invalidates_previous_cloud_cache():
    parser = MinerUParser()
    disabled = replace(CFG, normalize_tiny_scans=False)
    assert parser.signature(CFG).hash() != parser.signature(disabled).hash()
    assert "normalization" not in dict(parser.signature(disabled).params)
    assert parser.signature(replace(CFG, mode="local")) == parser.signature(
        replace(disabled, mode="local")
    )


def test_backend_uploads_copy_and_keeps_configuration(tmp_path, monkeypatch):
    from deeptutor.services.parsing.engines.mineru import backend, cloud

    source = scan(tmp_path / "scan.pdf")
    calls = []

    def parse(path, output, config, **kwargs):
        calls.append(path)
        assert path != source and path.name == source.name
        assert config is CFG
        with pymupdf.open(path) as doc:
            assert doc[0].rect.height == 768
        return output / path.stem

    monkeypatch.setattr(cloud, "parse_cloud", parse)
    assert (
        backend.parse_document_to_workdir(source, tmp_path / "out", config=CFG)
        == tmp_path / "out" / "scan"
    )
    assert len(calls) == 1 and not calls[0].exists()


@pytest.mark.asyncio
async def test_settings_enable_disable_and_legacy_save_preserves_opt_in(tmp_path, monkeypatch):
    from deeptutor.api.routers import settings
    from deeptutor.services.config.runtime_settings import RuntimeSettingsService
    from deeptutor.services.parsing.engines.mineru import config

    service = RuntimeSettingsService(tmp_path / "settings", process_env={})
    monkeypatch.setattr(settings, "_require_settings_admin", lambda: None)
    monkeypatch.setattr(settings, "get_runtime_settings_service", lambda: service)
    monkeypatch.setattr(settings, "_document_parsing_payload", service.load_document_parsing)
    monkeypatch.setattr(settings, "_mineru_settings_payload", service.load_mineru)
    monkeypatch.setattr(config, "load_mineru_settings", service.load_mineru)
    assert not config.resolve_mineru_config().normalize_tiny_scans
    await settings.update_document_parsing_settings(
        settings.DocumentParsingUpdate(engines={"mineru": {"normalize_tiny_scans": True}})
    )
    assert config.resolve_mineru_config().normalize_tiny_scans
    await settings.update_mineru_settings(settings.MinerUSettingsUpdate(language="en"))
    assert config.resolve_mineru_config().normalize_tiny_scans
    await settings.update_document_parsing_settings(
        settings.DocumentParsingUpdate(engines={"mineru": {"normalize_tiny_scans": False}})
    )
    assert not config.resolve_mineru_config().normalize_tiny_scans


@pytest.mark.asyncio
async def test_normalization_and_slicing_survive_settings_updates_and_profile_export(
    tmp_path, monkeypatch
):
    from dataclasses import replace

    from deeptutor.api.routers import settings
    from deeptutor.services.config.runtime_settings import RuntimeSettingsService
    from deeptutor.services.config.settings_profile import (
        export_settings_profile,
        review_settings_profile_import,
    )
    from deeptutor.services.parsing.engines.mineru import config
    from deeptutor.services.parsing.engines.mineru.engine import MinerUParser

    service = RuntimeSettingsService(tmp_path / "settings", process_env={})
    monkeypatch.setattr(settings, "_require_settings_admin", lambda: None)
    monkeypatch.setattr(settings, "get_runtime_settings_service", lambda: service)
    monkeypatch.setattr(settings, "_document_parsing_payload", service.load_document_parsing)
    monkeypatch.setattr(settings, "_mineru_settings_payload", service.load_mineru)
    monkeypatch.setattr(config, "load_mineru_settings", service.load_mineru)
    await settings.update_document_parsing_settings(
        settings.DocumentParsingUpdate(
            engines={
                "mineru": {"mode": "cloud", "normalize_tiny_scans": True, "max_pages_per_part": 90}
            }
        )
    )
    await settings.update_mineru_settings(
        settings.MinerUSettingsUpdate(mode="cloud", language="en")
    )
    effective = config.resolve_mineru_config()
    assert effective.normalize_tiny_scans is True
    assert effective.max_pages_per_part == 90
    exported = export_settings_profile(service=service, catalog={})
    portable = exported["profile"]["settings"]["document_parsing"]["engines"]["mineru"]
    assert portable["normalize_tiny_scans"] is True
    assert portable["max_pages_per_part"] == 90
    assert review_settings_profile_import(exported, service=service, catalog={})["summary"] == {
        "changed": 0,
        "unsupported": 0,
        "compatible": True,
    }
    parser = MinerUParser()
    signature = parser.signature(effective)
    assert signature != parser.signature(replace(effective, normalize_tiny_scans=False))
    assert signature != parser.signature(replace(effective, max_pages_per_part=180))
