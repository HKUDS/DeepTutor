"""The Docling worker must not degrade to upstream defaults silently.

``_build_converter`` falls back to a bare ``DocumentConverter()`` when Docling's
option API moves. Docling defaults ``do_ocr`` to True while DeepTutor defaults it
to False, so a silent fallback flips OCR on, changes the output and slows the run
with nothing in the log to explain it (#2518). A genuinely missing Docling install
is a different failure and must keep raising, not fall back.
"""

from __future__ import annotations

import sys
import types
from typing import Iterator

import pytest

from deeptutor.services.parsing.engines.docling import local_worker


class _StubConverter:
    """Records the format options the worker builds."""

    def __init__(self, format_options: dict | None = None) -> None:
        self.format_options = format_options or {}


class _StubPipelineOptions:
    def __init__(self) -> None:
        # Docling's own defaults, which the fallback inherits.
        self.do_ocr = True
        self.do_table_structure = True


class _StubFormatOption:
    def __init__(self, pipeline_options: object = None) -> None:
        self.pipeline_options = pipeline_options


def _install_docling_stubs(
    monkeypatch: pytest.MonkeyPatch,
    *,
    pipeline_options_factory=None,
    converter_factory=None,
) -> None:
    """Put a minimal ``docling`` package into ``sys.modules``.

    ``_build_converter`` imports Docling inside the function, so stubbing the
    modules is enough to exercise it without the multi-GB dependency.
    """

    docling = types.ModuleType("docling")
    datamodel = types.ModuleType("docling.datamodel")
    base_models = types.ModuleType("docling.datamodel.base_models")
    pipeline_options = types.ModuleType("docling.datamodel.pipeline_options")
    document_converter = types.ModuleType("docling.document_converter")

    class _InputFormat:
        PDF = "pdf"

    base_models.InputFormat = _InputFormat
    pipeline_options.PdfPipelineOptions = pipeline_options_factory or _StubPipelineOptions
    document_converter.DocumentConverter = converter_factory or _StubConverter
    document_converter.PdfFormatOption = _StubFormatOption

    for name, module in {
        "docling": docling,
        "docling.datamodel": datamodel,
        "docling.datamodel.base_models": base_models,
        "docling.datamodel.pipeline_options": pipeline_options,
        "docling.document_converter": document_converter,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)


@pytest.fixture
def stderr_lines() -> Iterator[list[str]]:
    """Collect what the worker writes to stderr."""

    collected: list[str] = []
    yield collected


def test_configured_options_are_applied_without_a_warning(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_docling_stubs(monkeypatch)

    converter = local_worker._build_converter(do_ocr=False, do_table_structure=True)

    option = converter.format_options["pdf"]
    assert option.pipeline_options.do_ocr is False
    assert option.pipeline_options.do_table_structure is True
    assert capsys.readouterr().err == ""


def test_option_failure_falls_back_and_reports_it(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A shifted option API still converts, but never silently."""

    def _explode() -> object:
        raise AttributeError("PdfPipelineOptions has no do_table_structure")

    _install_docling_stubs(monkeypatch, pipeline_options_factory=_explode)

    converter = local_worker._build_converter(do_ocr=False, do_table_structure=True)

    # The parse still runs, with upstream defaults.
    assert isinstance(converter, _StubConverter)
    assert converter.format_options == {}

    err = capsys.readouterr().err
    assert "Docling option setup failed" in err
    # The diagnostic names the failure and both dropped options (#2518).
    assert "AttributeError" in err
    assert "do_table_structure" in err
    assert "do_ocr=False" in err
    assert "do_table_structure=True" in err


def test_missing_docling_install_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing dependency is not an option-API difference and must not fall back.

    ``DocumentConverter`` itself is imported outside the ``try``, so an absent
    Docling install keeps raising instead of silently converting nothing.
    """

    for name in (
        "docling",
        "docling.datamodel",
        "docling.datamodel.base_models",
        "docling.datamodel.pipeline_options",
        "docling.document_converter",
    ):
        monkeypatch.setitem(sys.modules, name, None)

    with pytest.raises(ImportError):
        local_worker._build_converter(do_ocr=False, do_table_structure=False)


def test_older_docling_without_pipeline_options_still_degrades_loudly(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The option modules live inside the ``try``, so older releases still convert.

    This preserves the pre-#2518 behaviour; only the silence changes.
    """

    _install_docling_stubs(monkeypatch)
    monkeypatch.setitem(sys.modules, "docling.datamodel.pipeline_options", None)

    converter = local_worker._build_converter(do_ocr=False, do_table_structure=False)

    assert isinstance(converter, _StubConverter)
    err = capsys.readouterr().err
    assert "Docling option setup failed" in err


def test_fallback_warning_is_a_single_line(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The parent relays one line per read; keep the diagnostic on one line."""

    def _explode() -> object:
        raise RuntimeError("boom")

    _install_docling_stubs(monkeypatch, pipeline_options_factory=_explode)

    local_worker._build_converter(do_ocr=True, do_table_structure=False)

    err = capsys.readouterr().err
    assert len([line for line in err.splitlines() if line.strip()]) == 1
