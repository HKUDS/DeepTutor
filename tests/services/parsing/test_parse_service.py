from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.services.parsing import base, signature
import deeptutor.services.parsing.service as svc_mod
from deeptutor.services.parsing.service import ParseService
from deeptutor.services.parsing.types import ParserError


class _FakeParser:
    name = "fake"
    needs_local_models = False

    def __init__(self, *, ready: bool = True, sig: str = "v1", calls: list | None = None) -> None:
        self._ready = ready
        self._sig = sig
        self.calls = calls if calls is not None else []

    @classmethod
    def is_available(cls) -> bool:
        return True

    def resolve_config(self):
        return {}

    def supported_formats(self):
        return frozenset({".pdf"})

    def signature(self, _config):
        return signature.ParserSignature.build("fake", "1", {"v": self._sig})

    def is_ready(self, _config):
        return base.ReadinessReport(ready=self._ready, reason="gate", message="not ready")

    def parse(self, source_path: Path, workdir: Path, *, config, on_output=None) -> None:
        self.calls.append(source_path)
        (workdir / f"{source_path.stem}.md").write_text("# md", encoding="utf-8")


def _use(monkeypatch, parser) -> None:
    monkeypatch.setattr(svc_mod, "get_parser", lambda name: parser)


def _pdf(tmp_path: Path, data: bytes = b"%PDF data", name: str = "x.pdf") -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def test_cache_hit_skips_engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    parser = _FakeParser()
    _use(monkeypatch, parser)
    pdf = _pdf(tmp_path)
    service = ParseService(cache_root=tmp_path / "cache")

    first = service.parse(pdf, engine="fake")
    second = service.parse(pdf, engine="fake")

    assert len(parser.calls) == 1  # engine ran once; second call hit cache
    assert first.markdown == "# md"
    assert first.blocks is None
    assert first.workdir == second.workdir


def test_signature_change_busts_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pdf = _pdf(tmp_path)
    service = ParseService(cache_root=tmp_path / "cache")

    p1 = _FakeParser(sig="v1")
    _use(monkeypatch, p1)
    service.parse(pdf, engine="fake")

    p2 = _FakeParser(sig="v2")
    _use(monkeypatch, p2)
    service.parse(pdf, engine="fake")

    assert len(p1.calls) == 1 and len(p2.calls) == 1  # different signature → re-parse


def test_same_bytes_different_name_share_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parser = _FakeParser()
    _use(monkeypatch, parser)
    service = ParseService(cache_root=tmp_path / "cache")

    service.parse(_pdf(tmp_path, b"identical", "first.pdf"), engine="fake")
    service.parse(_pdf(tmp_path, b"identical", "second.pdf"), engine="fake")
    assert len(parser.calls) == 1


def test_not_ready_raises_before_parse(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    parser = _FakeParser(ready=False)
    _use(monkeypatch, parser)
    service = ParseService(cache_root=tmp_path / "cache")
    with pytest.raises(ParserError, match="not ready"):
        service.parse(_pdf(tmp_path), engine="fake")
    assert parser.calls == []


def test_unsupported_format_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    parser = _FakeParser()
    _use(monkeypatch, parser)
    service = ParseService(cache_root=tmp_path / "cache")
    with pytest.raises(ParserError, match="support"):
        service.parse(_pdf(tmp_path, b"data", "notes.txt"), engine="fake")


def test_supports_is_a_side_effect_free_suffix_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parser = _FakeParser()
    _use(monkeypatch, parser)
    service = ParseService(cache_root=tmp_path / "cache")

    assert service.supports(tmp_path / "missing.pdf", engine="fake") is True
    assert service.supports(tmp_path / "missing.png", engine="fake") is False
    assert parser.calls == []


def test_supports_compound_suffixes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    parser = _FakeParser()
    parser.supported_formats = lambda: frozenset({".tar.gz", ".dclg.xml"})
    _use(monkeypatch, parser)
    service = ParseService(cache_root=tmp_path / "cache")

    assert service.supports(tmp_path / "missing.TAR.GZ", engine="fake") is True
    assert service.supports(tmp_path / "missing.DCLG.XML", engine="fake") is True
    assert service.supports(tmp_path / "missing.gz", engine="fake") is False


def test_empty_supported_formats_delegates_to_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parser = _FakeParser()
    parser.supported_formats = lambda: frozenset()
    _use(monkeypatch, parser)
    service = ParseService(cache_root=tmp_path / "cache")

    assert service.supports(tmp_path / "custom.vendor-format", engine="fake") is True


def test_missing_file_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use(monkeypatch, _FakeParser())
    service = ParseService(cache_root=tmp_path / "cache")
    with pytest.raises(ParserError):
        service.parse(tmp_path / "ghost.pdf", engine="fake")


# ---------------------------------------------------------------------------
# Implicit-engine fallback for unsupported suffixes (#1502)
# ---------------------------------------------------------------------------


class _NamedFakeParser(_FakeParser):
    def __init__(self, *, name: str, formats: frozenset[str], **kwargs) -> None:
        super().__init__(**kwargs)
        self.name = name
        self._formats = formats

    def supported_formats(self):
        return self._formats


def _use_map(monkeypatch: pytest.MonkeyPatch, parsers: dict) -> None:
    def _get(name: str):
        if name not in parsers:
            raise KeyError(name)
        return parsers[name]

    monkeypatch.setattr(svc_mod, "get_parser", _get)


def _txt(tmp_path: Path, name: str = "notes.txt") -> Path:
    path = tmp_path / name
    path.write_text("plain text", encoding="utf-8")
    return path


def test_implicit_engine_falls_back_for_unsupported_suffix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MinerU-style engine selected globally + a .txt file → the text-capable
    engine parses it instead of failing the whole ingest batch (#1502)."""
    primary = _NamedFakeParser(name="mineru", formats=frozenset({".pdf", ".docx"}))
    text_engine = _NamedFakeParser(name="text_only", formats=frozenset(), sig="text-v1")
    _use_map(monkeypatch, {"mineru": primary, "text_only": text_engine})
    monkeypatch.setattr(svc_mod, "load_document_parsing_settings", lambda: {"engine": "mineru"})
    txt = _txt(tmp_path)
    service = ParseService(cache_root=tmp_path / "cache")

    result = service.parse(txt)

    assert result.engine == "text_only"
    assert primary.calls == []


def test_explicit_engine_keeps_the_loud_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A caller that pinned the engine by name gets the current hard error."""
    primary = _NamedFakeParser(name="mineru", formats=frozenset({".pdf", ".docx"}))
    text_engine = _NamedFakeParser(name="text_only", formats=frozenset())
    _use_map(monkeypatch, {"mineru": primary, "text_only": text_engine})
    txt = _txt(tmp_path)
    service = ParseService(cache_root=tmp_path / "cache")

    with pytest.raises(ParserError, match="doesn't support"):
        service.parse(txt, engine="mineru")
    assert text_engine.calls == []


def test_fallback_prefers_the_documented_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """text_only wins over markitdown/tika when all are installed."""
    primary = _NamedFakeParser(name="mineru", formats=frozenset({".pdf"}))
    markitdown = _NamedFakeParser(name="markitdown", formats=frozenset({".txt"}))
    text_engine = _NamedFakeParser(name="text_only", formats=frozenset({".txt"}))
    _use_map(
        monkeypatch,
        {"mineru": primary, "text_only": text_engine, "markitdown": markitdown},
    )
    monkeypatch.setattr(svc_mod, "load_document_parsing_settings", lambda: {"engine": "mineru"})
    service = ParseService(cache_root=tmp_path / "cache")

    result = service.parse(_txt(tmp_path))

    assert result.engine == "text_only"
    assert markitdown.calls == []


def test_no_fallback_engine_raises_the_original_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing installed can take the file → the loud error is unchanged."""
    primary = _NamedFakeParser(name="mineru", formats=frozenset({".pdf"}))
    _use_map(monkeypatch, {"mineru": primary})
    monkeypatch.setattr(svc_mod, "load_document_parsing_settings", lambda: {"engine": "mineru"})
    service = ParseService(cache_root=tmp_path / "cache")

    with pytest.raises(ParserError, match="doesn't support"):
        service.parse(_txt(tmp_path))


def test_fallback_skips_uninstalled_engines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """text_only missing → markitdown is tried next without failing."""
    primary = _NamedFakeParser(name="mineru", formats=frozenset({".pdf"}))
    markitdown = _NamedFakeParser(name="markitdown", formats=frozenset({".txt"}))
    _use_map(monkeypatch, {"mineru": primary, "markitdown": markitdown})
    monkeypatch.setattr(svc_mod, "load_document_parsing_settings", lambda: {"engine": "mineru"})
    service = ParseService(cache_root=tmp_path / "cache")

    result = service.parse(_txt(tmp_path))

    assert result.engine == "markitdown"
