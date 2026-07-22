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


def test_missing_file_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use(monkeypatch, _FakeParser())
    service = ParseService(cache_root=tmp_path / "cache")
    with pytest.raises(ParserError):
        service.parse(tmp_path / "ghost.pdf", engine="fake")
