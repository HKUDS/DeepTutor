"""Unit tests for the Docling → content_list block mapping (#2518).

Docling objects are duck-typed fakes mirroring the real docling-core 2.106
shapes — the mapper must be testable (and importable) without a real Docling
install or model download. One test additionally exercises the real
docling-core API when it is installed and skips otherwise.
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


class _CoordOrigin:
    """Enum-like fake mirroring ``docling_core.types.doc.CoordOrigin``."""

    def __init__(self, value: str) -> None:
        self.value = value


class _BBox:
    def __init__(
        self,
        l: float,  # noqa: E741
        t: float,
        r: float,
        b: float,
        coord_origin: str | _CoordOrigin | None = None,
    ) -> None:
        self.l, self.t, self.r, self.b = l, t, r, b
        if coord_origin is not None:
            self.coord_origin = coord_origin


class _ProvRecord:
    """Duck-typed ``ProvenanceItem``: 1-based page_no, bbox, charspan."""

    def __init__(self, page_no: int | None = 1, bbox: _BBox | None = None) -> None:
        self.page_no = page_no
        self.bbox = bbox
        self.charspan = (0, 0)


class _LegacyProv:
    """Pre-schema-v2 single record carrying the legacy ``page`` attribute."""

    def __init__(self, page: int | None = 1, bbox: _BBox | None = None) -> None:
        self.page = page
        self.bbox = bbox


_UNSET = object()


class _TextItem:
    def __init__(
        self,
        label: str,
        text: str = "",
        *,
        page: int | None = 1,
        bbox: _BBox | None = None,
        prov: object = _UNSET,
    ) -> None:
        self.label = _Label(label)
        self.text = text
        # Real Docling shape: prov is a list of provenance records. Tests can
        # override it with a single record, None, or an empty list.
        self.prov = [_ProvRecord(page_no=page, bbox=bbox)] if prov is _UNSET else prov


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
    """Duck-typed ``TableItem`` mirroring docling-core 2.106 exporters.

    ``export_to_html`` returns ``""`` unless the owning document is passed
    (the real deprecated doc-less call does exactly that), and
    ``export_to_markdown`` accepts ``doc`` as well. ``fail_html`` simulates
    an exporter that raises even with ``doc``.
    """

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
        self.prov = [_ProvRecord(page_no=page)]

    def export_to_html(self, doc=None, add_caption: bool = True) -> str:
        if doc is None:
            return ""
        if self._fail_html:
            raise RuntimeError("html export unavailable")
        return self._html

    def export_to_markdown(self, doc=None) -> str:
        return self._markdown


class _DoclessHtmlTableItem(_TableItem):
    """Old-shape exporter whose signature takes no ``doc`` parameter."""

    def export_to_html(self) -> str:  # type: ignore[override]
        return self._html


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
        self.prov = [_ProvRecord(page_no=page, bbox=_BBox(0.1, 0.2, 0.3, 0.4))]


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


def test_table_exporters_receive_the_owning_document() -> None:
    """Regression (#2518): docling-core 2.106's ``export_to_html()`` returns
    "" for the deprecated doc-less call, so the mapper must hand over the
    owning document or every table flattens to markdown. The markdown
    fallback exporter must receive it too."""
    received: list[object] = []

    class _TrackingTable(_TableItem):
        def export_to_html(self, doc=None, add_caption: bool = True) -> str:
            received.append(doc)
            if self._fail_html:
                raise RuntimeError("html export unavailable")
            return self._html

        def export_to_markdown(self, doc=None) -> str:
            received.append(doc)
            return self._markdown

    document = _FakeDocument([(_TrackingTable(), 1)])
    blocks = build_content_list(document)
    assert received == [document]
    assert blocks == [
        {
            "type": "table",
            "table_body": "<table><tr><td>a</td></tr></table>",
            "num_rows": 2,
            "num_cols": 3,
            "page_idx": 0,
        }
    ]

    # HTML failure degrades to markdown — which still gets the document.
    received.clear()
    failing = _FakeDocument([(_TrackingTable(fail_html=True), 1)])
    assert build_content_list(failing) == [{"type": "text", "text": "| a |", "page_idx": 0}]
    assert received == [failing, failing]


def test_docless_html_exporter_still_yields_html() -> None:
    """An exporter whose signature takes no ``doc`` keeps working (the
    doc-passing call degrades to a doc-less one)."""
    document = _FakeDocument([(_DoclessHtmlTableItem(), 1)])

    blocks = build_content_list(document)

    assert blocks == [
        {
            "type": "table",
            "table_body": "<table><tr><td>a</td></tr></table>",
            "num_rows": 2,
            "num_cols": 3,
            "page_idx": 0,
        }
    ]


def test_real_docling_core_table_keeps_merged_cells() -> None:
    """End-to-end against the real docling-core API (when installed): a
    merged header cell survives as a rowspan attribute in the table body."""
    pytest.importorskip("docling_core.types.doc")
    from docling_core.types.doc import (
        BoundingBox,
        CoordOrigin,
        DocItemLabel,
        DoclingDocument,
        ProvenanceItem,
        TableCell,
        TableData,
    )

    document = DoclingDocument(name="merged-cell-test")
    # 2x2 grid with a vertically merged header cell in column 0.
    data = TableData(
        num_rows=2,
        num_cols=2,
        table_cells=[
            TableCell(
                row_span=2,
                start_row_offset_idx=0,
                end_row_offset_idx=2,
                start_col_offset_idx=0,
                end_col_offset_idx=1,
                text="merged",
                column_header=True,
            ),
            TableCell(
                start_row_offset_idx=0,
                end_row_offset_idx=1,
                start_col_offset_idx=1,
                end_col_offset_idx=2,
                text="top",
                column_header=True,
            ),
            TableCell(
                start_row_offset_idx=1,
                end_row_offset_idx=2,
                start_col_offset_idx=1,
                end_col_offset_idx=2,
                text="bottom",
            ),
        ],
    )
    document.add_table(
        data=data,
        prov=ProvenanceItem(
            page_no=1,
            bbox=BoundingBox(l=10.0, t=20.0, r=30.0, b=40.0, coord_origin=CoordOrigin.TOPLEFT),
            charspan=(0, 0),
        ),
        label=DocItemLabel.TABLE,
    )

    # The upstream behavior this mapper defends against: the doc-less
    # deprecated call returns "".
    assert document.tables[0].export_to_html() == ""

    blocks = build_content_list(document)

    (table_block,) = (block for block in blocks if block["type"] == "table")
    assert '<th rowspan="2">merged</th>' in table_block["table_body"]
    assert table_block["num_rows"] == 2
    assert table_block["num_cols"] == 2
    assert table_block["page_idx"] == 0
    assert table_block["bbox"] == [10.0, 20.0, 30.0, 40.0]


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


# ---------------------------------------------------------------------------
# Provenance records (real shape: prov is a list with page_no + bbox)
# ---------------------------------------------------------------------------


def test_prov_list_records_yield_page_idx_and_bbox() -> None:
    document = _FakeDocument(
        [(_TextItem("paragraph", "text", page=3, bbox=_BBox(1.5, 2.5, 3.5, 4.5)), 1)]
    )

    assert build_content_list(document) == [
        {"type": "text", "text": "text", "page_idx": 2, "bbox": [1.5, 2.5, 3.5, 4.5]}
    ]


def test_prov_records_on_one_page_union_their_bboxes() -> None:
    item = _TextItem(
        "paragraph",
        "text",
        prov=[
            _ProvRecord(page_no=2, bbox=_BBox(10.0, 20.0, 30.0, 40.0)),
            _ProvRecord(page_no=2, bbox=_BBox(5.0, 25.0, 35.0, 45.0)),
            # A continuation on another page must not leak into this bbox.
            _ProvRecord(page_no=3, bbox=_BBox(99.0, 99.0, 99.0, 99.0)),
        ],
    )
    document = _FakeDocument([(item, 1)])

    assert build_content_list(document) == [
        {"type": "text", "text": "text", "page_idx": 1, "bbox": [5.0, 20.0, 35.0, 45.0]}
    ]


def test_prov_bottomleft_bbox_keeps_orientation() -> None:
    item = _TextItem(
        "paragraph",
        "text",
        prov=[
            _ProvRecord(
                page_no=1,
                bbox=_BBox(1.0, 4.0, 2.0, 3.0, coord_origin=_CoordOrigin("BOTTOMLEFT")),
            ),
            _ProvRecord(
                page_no=1,
                bbox=_BBox(1.5, 3.5, 4.0, 2.0, coord_origin=_CoordOrigin("BOTTOMLEFT")),
            ),
        ],
    )
    document = _FakeDocument([(item, 1)])

    # y values {4, 3, 3.5, 2}: the union spans 2..4; BOTTOMLEFT emits t > b.
    assert build_content_list(document) == [
        {"type": "text", "text": "text", "page_idx": 0, "bbox": [1.0, 4.0, 4.0, 2.0]}
    ]


def test_single_record_and_legacy_prov_are_tolerated() -> None:
    document = _FakeDocument(
        [
            (
                _TextItem("paragraph", "one", prov=_ProvRecord(page_no=2, bbox=_BBox(1, 2, 3, 4))),
                1,
            ),
            (_TextItem("paragraph", "two", prov=_LegacyProv(page=5)), 1),
        ]
    )

    assert build_content_list(document) == [
        {"type": "text", "text": "one", "page_idx": 1, "bbox": [1.0, 2.0, 3.0, 4.0]},
        {"type": "text", "text": "two", "page_idx": 4},
    ]


def test_missing_or_empty_prov_yields_no_page_or_bbox() -> None:
    document = _FakeDocument(
        [
            (_TextItem("paragraph", "none", prov=None), 1),
            (_TextItem("paragraph", "empty", prov=[]), 1),
        ]
    )

    assert build_content_list(document) == [
        {"type": "text", "text": "none"},
        {"type": "text", "text": "empty"},
    ]


# ---------------------------------------------------------------------------
# List grouping across pages
# ---------------------------------------------------------------------------


def test_list_items_on_different_pages_split_into_blocks() -> None:
    document = _FakeDocument(
        [
            (_TextItem("list_item", "one", page=1), 2),
            (_TextItem("list_item", "two", page=1), 2),
            (_TextItem("list_item", "three", page=2), 2),
            (_TextItem("paragraph", "after", page=2), 1),
        ]
    )

    assert build_content_list(document) == [
        {"type": "list", "list_items": ["one", "two"], "page_idx": 0},
        {"type": "list", "list_items": ["three"], "page_idx": 1},
        {"type": "text", "text": "after", "page_idx": 1},
    ]


def test_list_block_bbox_unions_grouped_item_bboxes() -> None:
    document = _FakeDocument(
        [
            (_TextItem("list_item", "one", page=1, bbox=_BBox(10, 20, 30, 40)), 2),
            (_TextItem("list_item", "two", page=1, bbox=_BBox(5, 8, 12, 50)), 2),
        ]
    )

    assert build_content_list(document) == [
        {
            "type": "list",
            "list_items": ["one", "two"],
            "page_idx": 0,
            "bbox": [5.0, 8.0, 30.0, 50.0],
        }
    ]


def test_list_block_bbox_union_keeps_bottomleft_orientation() -> None:
    document = _FakeDocument(
        [
            (
                _TextItem(
                    "list_item",
                    "one",
                    page=1,
                    bbox=_BBox(10, 40, 30, 20, coord_origin="BOTTOMLEFT"),
                ),
                2,
            ),
            (
                _TextItem(
                    "list_item",
                    "two",
                    page=1,
                    bbox=_BBox(5, 35, 12, 8, coord_origin="BOTTOMLEFT"),
                ),
                2,
            ),
        ]
    )

    # x: min(l)=5, max(r)=30; y values {40, 20, 35, 8} span 8..40 and
    # BOTTOMLEFT emits t > b.
    assert build_content_list(document) == [
        {
            "type": "list",
            "list_items": ["one", "two"],
            "page_idx": 0,
            "bbox": [5.0, 40.0, 30.0, 8.0],
        }
    ]


# ---------------------------------------------------------------------------
# List grouping across known/unknown page transitions (#2518 regression)
# ---------------------------------------------------------------------------


def test_list_unknown_then_known_pages_never_merge() -> None:
    """Regression: [unknown, page1, page2] used to merge into one block with
    combined coordinates because a ``None`` pending page disabled the page
    check. Every known/unknown transition must flush."""
    document = _FakeDocument(
        [
            (_TextItem("list_item", "mystery", prov=None), 2),
            (_TextItem("list_item", "p1", page=1, bbox=_BBox(1, 2, 3, 4)), 2),
            (_TextItem("list_item", "p2", page=2, bbox=_BBox(5, 6, 7, 8)), 2),
        ]
    )

    assert build_content_list(document) == [
        {"type": "list", "list_items": ["mystery"]},
        {"type": "list", "list_items": ["p1"], "page_idx": 0, "bbox": [1.0, 2.0, 3.0, 4.0]},
        {"type": "list", "list_items": ["p2"], "page_idx": 1, "bbox": [5.0, 6.0, 7.0, 8.0]},
    ]


def test_list_known_unknown_known_split_into_three_blocks() -> None:
    """[p1, unknown, p1] flushes on both transitions — the trailing p1 never
    merges back into the first group."""
    document = _FakeDocument(
        [
            (_TextItem("list_item", "p1", page=1), 2),
            (_TextItem("list_item", "mystery", prov=None), 2),
            (_TextItem("list_item", "p1-again", page=1), 2),
        ]
    )

    assert build_content_list(document) == [
        {"type": "list", "list_items": ["p1"], "page_idx": 0},
        {"type": "list", "list_items": ["mystery"]},
        {"type": "list", "list_items": ["p1-again"], "page_idx": 0},
    ]


def test_list_consecutive_unknown_items_stay_one_block() -> None:
    document = _FakeDocument(
        [
            (_TextItem("list_item", "one", prov=None), 2),
            (_TextItem("list_item", "two", prov=[]), 2),
        ]
    )

    assert build_content_list(document) == [{"type": "list", "list_items": ["one", "two"]}]


def test_list_known_then_unknown_flushes() -> None:
    document = _FakeDocument(
        [
            (_TextItem("list_item", "p2", page=2, bbox=_BBox(9, 9, 9, 9)), 2),
            (_TextItem("list_item", "mystery", prov=None), 2),
        ]
    )

    assert build_content_list(document) == [
        {"type": "list", "list_items": ["p2"], "page_idx": 1, "bbox": [9.0, 9.0, 9.0, 9.0]},
        {"type": "list", "list_items": ["mystery"]},
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

    assert docling_engine.CONTENT_LIST_SCHEMA_VERSION == 3
    local_before = parser.signature(DoclingConfig(mode="local")).hash()
    remote_config = DoclingConfig(mode="remote", api_base_url="http://host:5001")
    remote_before = parser.signature(remote_config).hash()

    monkeypatch.setattr(docling_engine, "CONTENT_LIST_SCHEMA_VERSION", 99)

    assert parser.signature(DoclingConfig(mode="local")).hash() != local_before
    assert parser.signature(remote_config).hash() == remote_before
