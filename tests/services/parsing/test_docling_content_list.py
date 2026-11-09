"""Unit tests for the Docling → content_list block mapping (#2518).

All Docling objects are duck-typed fakes — the mapper must be testable (and
importable) without a real Docling install or model download.
"""

from __future__ import annotations

from pathlib import Path
import sys
import types

import pytest

from deeptutor.services.parsing import cache as parse_cache
from deeptutor.services.parsing.engines import factory
from deeptutor.services.parsing.engines.docling import local_worker
from deeptutor.services.parsing.engines.docling.config import DoclingConfig
from deeptutor.services.parsing.engines.docling.content_list import (
    build_content_list,
    write_content_list,
)

# ---------------------------------------------------------------------------
# Fake Docling item tree
# ---------------------------------------------------------------------------


class _Label:
    def __init__(self, value: str) -> None:
        self.value = value


class _BBox:
    def __init__(self, l: float, t: float, r: float, b: float) -> None:  # noqa: E741
        self.l, self.t, self.r, self.b = l, t, r, b


class _Prov:
    def __init__(self, page: int | None = 1, bbox: _BBox | None = None) -> None:
        self.page = page
        self.bbox = bbox


class _TextItem:
    def __init__(
        self,
        label: str,
        text: str = "",
        *,
        page: int | None = 1,
        bbox: _BBox | None = None,
    ) -> None:
        self.label = _Label(label)
        self.text = text
        self.prov = _Prov(page=page, bbox=bbox)


class _Ref:
    """Caption ref that resolves against the document, like RefItem."""

    def __init__(self, text: str) -> None:
        self._text = text

    def resolve(self, document) -> _TextItem:
        return _TextItem("caption", self._text)


class _TableData:
    def __init__(self, rows: int, cols: int) -> None:
        self.num_rows = rows
        self.num_cols = cols


class _TableItem:
    label = _Label("table")

    def __init__(
        self,
        html: str = "<table><tr><td>a</td></tr></table>",
        *,
        markdown: str = "| a |",
        fail_html: bool = False,
        captions: list[_Ref] | None = None,
        page: int | None = 1,
    ) -> None:
        self._html = html
        self._markdown = markdown
        self._fail_html = fail_html
        self.captions = captions or []
        self.data = _TableData(2, 3)
        self.prov = _Prov(page=page)

    def export_to_html(self) -> str:
        if self._fail_html:
            raise RuntimeError("html export unavailable")
        return self._html

    def export_to_markdown(self) -> str:
        return self._markdown


class _PilImage:
    def __init__(self) -> None:
        self.saved_to: list[Path] = []

    def save(self, path) -> None:
        target = Path(path)
        target.write_bytes(b"fake-crop")
        self.saved_to.append(target)


class _FakeImage:
    def __init__(self, fmt: str = "image/png") -> None:
        self.format = fmt
        self.pil_image = _PilImage()


class _PictureItem:
    label = _Label("picture")

    def __init__(
        self,
        image: _FakeImage | None,
        *,
        captions: list[_Ref] | None = None,
        page: int | None = 2,
    ) -> None:
        self.image = image
        self.captions = captions or []
        self.prov = _Prov(page=page, bbox=_BBox(0.1, 0.2, 0.3, 0.4))


class _FakeDocument:
    def __init__(self, items: list[tuple[object, int]]) -> None:
        self._items = items
        self.markdown = "# Exported\n\nbody\n"

    def iterate_items(self):
        return iter(self._items)

    def export_to_markdown(self) -> str:
        return self.markdown


# ---------------------------------------------------------------------------
# build_content_list
# ---------------------------------------------------------------------------


def test_maps_headings_paragraphs_and_provenance() -> None:
    document = _FakeDocument(
        [
            (_TextItem("title", "Fourier Analysis"), 1),
            (_TextItem("section_header", "Background", page=1), 2),
            (
                _TextItem("paragraph", "The transform maps time to frequency.", page=1),
                2,
            ),
            (_TextItem("section_header", "Deep heading", page=3), 9),
        ]
    )

    blocks = build_content_list(document)

    assert blocks == [
        {"type": "text", "text": "Fourier Analysis", "text_level": 1, "page_idx": 0},
        {"type": "text", "text": "Background", "text_level": 2, "page_idx": 0},
        {
            "type": "text",
            "text": "The transform maps time to frequency.",
            "page_idx": 0,
        },
        {"type": "text", "text": "Deep heading", "text_level": 6, "page_idx": 2},
    ]


def test_maps_table_with_html_body_and_captions() -> None:
    table = _TableItem(captions=[_Ref("Table 1: results")], page=4)
    document = _FakeDocument([(table, 1)])

    blocks = build_content_list(document)

    assert blocks == [
        {
            "type": "table",
            "table_body": "<table><tr><td>a</td></tr></table>",
            "num_rows": 2,
            "num_cols": 3,
            "table_caption": ["Table 1: results"],
            "page_idx": 3,
        }
    ]


def test_table_html_failure_degrades_to_markdown_text() -> None:
    table = _TableItem(fail_html=True)
    document = _FakeDocument([(table, 1)])

    blocks = build_content_list(document)

    assert blocks == [{"type": "text", "text": "| a |", "page_idx": 0}]


def test_picture_crop_saved_and_referenced(tmp_path: Path) -> None:
    picture = _PictureItem(_FakeImage("image/png"), captions=[_Ref("Fig. 1")])
    picture_without_crop = _PictureItem(None)
    document = _FakeDocument([(picture, 1), (picture_without_crop, 1)])

    blocks = build_content_list(document, save_images_to=tmp_path, image_prefix="doc")

    # A picture without a crop is skipped: an image block with no asset
    # would break downstream asset resolution.
    assert blocks == [
        {
            "type": "image",
            "img_path": "images/doc_000.png",
            "image_caption": ["Fig. 1"],
            "page_idx": 1,
            "bbox": [0.1, 0.2, 0.3, 0.4],
        }
    ]
    assert (tmp_path / "doc_000.png").read_bytes() == b"fake-crop"


def test_formula_maps_to_equation_only_with_latex() -> None:
    document = _FakeDocument(
        [
            (_TextItem("formula", r"\hat{f}(\omega)", page=2), 1),
            (_TextItem("formula", "", page=2), 1),  # no LaTeX → never invented
        ]
    )

    blocks = build_content_list(document)

    assert blocks == [{"type": "equation", "text": r"\hat{f}(\omega)", "page_idx": 1}]


def test_furniture_and_chrome_labels_are_skipped() -> None:
    document = _FakeDocument(
        [
            (_TextItem("page_header", "CONFIDENTIAL DRAFT"), 1),
            (_TextItem("page_footer", "ACME Corp"), 1),
            (_TextItem("page_number", "7"), 1),
            (_TextItem("paragraph", "real body text", page=7), 1),
        ]
    )

    blocks = build_content_list(document)

    assert blocks == [
        {"type": "text", "text": "real body text", "page_idx": 6},
    ]


def test_consecutive_list_items_group_into_one_block() -> None:
    document = _FakeDocument(
        [
            (_TextItem("list_item", "first", page=1), 2),
            (_TextItem("list_item", "second", page=1), 2),
            (_TextItem("paragraph", "interrupt", page=1), 1),
            (_TextItem("list_item", "third", page=2), 2),
        ]
    )

    blocks = build_content_list(document)

    assert blocks == [
        {"type": "list", "list_items": ["first", "second"], "page_idx": 0},
        {"type": "text", "text": "interrupt", "page_idx": 0},
        {"type": "list", "list_items": ["third"], "page_idx": 1},
    ]


def test_code_items_carry_code_body() -> None:
    document = _FakeDocument([(_TextItem("code", "print('hi')"), 1)])

    assert build_content_list(document) == [
        {"type": "code", "code_body": "print('hi')", "page_idx": 0}
    ]


def test_unknown_labels_degrade_to_text_or_are_dropped() -> None:
    document = _FakeDocument(
        [
            (_TextItem("abstract", "We study parsing."), 1),
            (_TextItem("value", ""), 1),  # no text → dropped, not an empty block
        ]
    )

    assert build_content_list(document) == [
        {"type": "text", "text": "We study parsing.", "page_idx": 0}
    ]


def test_empty_document_maps_to_no_blocks(tmp_path: Path) -> None:
    document = _FakeDocument([])

    assert build_content_list(document) == []
    assert write_content_list(document, tmp_path, stem="doc") is None
    assert not (tmp_path / "doc_content_list.json").exists()


# ---------------------------------------------------------------------------
# write_content_list + cache loader integration
# ---------------------------------------------------------------------------


def test_write_content_list_produces_a_mineru_shaped_bundle(tmp_path: Path) -> None:
    document = _FakeDocument(
        [
            (_TextItem("title", "Report", page=1), 1),
            (_TableItem(page=1), 1),
            (_PictureItem(_FakeImage(), page=1), 1),
            (_TextItem("formula", "E=mc^2", page=1), 1),
        ]
    )
    workdir = tmp_path / "parsed"
    workdir.mkdir()
    # The worker always writes the markdown export beside the blocks.
    (workdir / "report.md").write_text("# Report\n", encoding="utf-8")

    blocks = write_content_list(document, workdir, stem="report")

    assert blocks is not None and len(blocks) == 4
    assert (workdir / "report_content_list.json").is_file()
    assert (workdir / "images" / "report_000.png").is_file()

    markdown, loaded_blocks, asset_dir = parse_cache.load_ir(workdir)
    assert markdown == "# Report\n"
    assert loaded_blocks is not None
    # load_ir anchors relative img_paths at the content dir (#624 contract),
    # so compare everything else field-by-field.
    expected_image_block = dict(blocks[2], img_path=str(workdir / "images" / "report_000.png"))
    assert loaded_blocks == [*blocks[:2], expected_image_block, blocks[3]]
    assert asset_dir == workdir / "images"


# ---------------------------------------------------------------------------
# Worker wiring
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, document: _FakeDocument) -> None:
        self.document = document


class _FakeConverter:
    def __init__(self, document: _FakeDocument) -> None:
        self._document = document

    def convert(self, _path: str) -> _FakeResult:
        return _FakeResult(self._document)


def test_worker_convert_writes_markdown_and_content_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "lesson.pdf"
    source.write_bytes(b"%PDF-1.4 fake")
    workdir = tmp_path / "out"
    document = _FakeDocument(
        [
            (_TextItem("title", "Lesson", page=1), 1),
            (_TextItem("formula", "a^2+b^2=c^2", page=1), 1),
        ]
    )
    monkeypatch.setattr(
        local_worker, "_build_converter", lambda **_kwargs: _FakeConverter(document)
    )

    local_worker._convert(source, workdir, do_ocr=False, do_table_structure=True)

    assert (workdir / "lesson.md").read_text(encoding="utf-8") == document.markdown
    content = (workdir / "lesson_content_list.json").read_text(encoding="utf-8")
    assert '"type": "equation"' in content


def test_worker_convert_keeps_markdown_only_without_structure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "empty.pdf"
    source.write_bytes(b"%PDF-1.4 fake")
    workdir = tmp_path / "out"
    monkeypatch.setattr(
        local_worker, "_build_converter", lambda **_kwargs: _FakeConverter(_FakeDocument([]))
    )

    local_worker._convert(source, workdir, do_ocr=False, do_table_structure=True)

    assert (workdir / "empty.md").is_file()
    assert not (workdir / "empty_content_list.json").exists()


def test_worker_convert_survives_mapping_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    source = tmp_path / "broken.pdf"
    source.write_bytes(b"%PDF-1.4 fake")
    workdir = tmp_path / "out"

    class _BrokenDocument(_FakeDocument):
        def iterate_items(self):
            raise RuntimeError("tree exploded")

    document = _BrokenDocument([(_TextItem("title", "x"), 1)])
    monkeypatch.setattr(
        local_worker, "_build_converter", lambda **_kwargs: _FakeConverter(document)
    )

    local_worker._convert(source, workdir, do_ocr=False, do_table_structure=True)

    assert (workdir / "broken.md").is_file()
    assert not (workdir / "broken_content_list.json").exists()
    assert "content-list mapping failed" in capsys.readouterr().out


def test_build_converter_enables_picture_crops(monkeypatch: pytest.MonkeyPatch) -> None:
    """Picture crops must be requested so image blocks have assets."""
    created: dict = {}

    class _PipelineOptions:
        def __init__(self) -> None:
            self.do_ocr = True
            self.do_table_structure = True
            self.generate_picture_images = False
            self.images_scale = 1.0

    class _PdfFormatOption:
        def __init__(self, pipeline_options=None) -> None:
            self.pipeline_options = pipeline_options

    class _DocumentConverter:
        def __init__(self, format_options=None) -> None:
            created["format_options"] = format_options

    base_models = types.ModuleType("docling.datamodel.base_models")

    class _InputFormat:
        PDF = "pdf"

    base_models.InputFormat = _InputFormat
    pipeline_mod = types.ModuleType("docling.datamodel.pipeline_options")
    pipeline_mod.PdfPipelineOptions = _PipelineOptions
    converter_mod = types.ModuleType("docling.document_converter")
    converter_mod.DocumentConverter = _DocumentConverter
    converter_mod.PdfFormatOption = _PdfFormatOption

    for name, module in (
        ("docling", types.ModuleType("docling")),
        ("docling.datamodel", types.ModuleType("docling.datamodel")),
        ("docling.datamodel.base_models", base_models),
        ("docling.datamodel.pipeline_options", pipeline_mod),
        ("docling.document_converter", converter_mod),
    ):
        monkeypatch.setitem(sys.modules, name, module)

    local_worker._build_converter(do_ocr=False, do_table_structure=True)

    options = created["format_options"]["pdf"].pipeline_options
    assert options.generate_picture_images is True
    assert options.images_scale == 2.0
    assert options.do_ocr is False
    assert options.do_table_structure is True


# ---------------------------------------------------------------------------
# Parser signature
# ---------------------------------------------------------------------------


def test_local_signature_tracks_content_list_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    """A mapping change must invalidate markdown-only local caches, while the
    unchanged remote output keeps its signature."""
    from deeptutor.services.parsing.engines.docling import engine as docling_engine

    parser = factory.get_parser("docling")

    local_before = parser.signature(DoclingConfig(mode="local")).hash()
    remote_config = DoclingConfig(mode="remote", api_base_url="http://host:5001")
    remote_before = parser.signature(remote_config).hash()

    monkeypatch.setattr(docling_engine, "CONTENT_LIST_SCHEMA_VERSION", 2)

    assert parser.signature(DoclingConfig(mode="local")).hash() != local_before
    assert parser.signature(remote_config).hash() == remote_before
