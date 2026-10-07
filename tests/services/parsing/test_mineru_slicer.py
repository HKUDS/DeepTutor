"""Tests for the MinerU cloud auto-slicer (oversized PDF → parts → merged artifacts)."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Callable
import zipfile

from pypdf import PdfReader, PdfWriter
import pytest

from deeptutor.services.parsing.engines.mineru import cloud as mineru_cloud
from deeptutor.services.parsing.engines.mineru import config as mineru_config
from deeptutor.services.parsing.engines.mineru.config import (
    MAX_PAGES_PER_PART_CEILING,
    MinerUConfig,
)

CLOUD_CFG = MinerUConfig(mode="cloud", api_token="tok")

# Progress substrings that only the auto-slicing path emits.
_SLICING_MARKERS = ("auto-splitting", "parsing part", "merging part")


@pytest.fixture(autouse=True)
def isolated_checkpoints(tmp_path, monkeypatch):
    from deeptutor.services.parsing.engines.mineru import checkpoints

    monkeypatch.setattr(checkpoints, "checkpoint_root", lambda: tmp_path / "checkpoints")


def _make_pdf(path: Path, pages: int) -> Path:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=612, height=792)
    with open(path, "wb") as out:
        writer.write(out)
    return path


def _fake_archive_bytes(
    name: str,
    md_text: str,
    images: dict[str, bytes] | None = None,
    content_items: list | None = None,
) -> bytes:
    """Build a zip shaped like a MinerU cloud result for one input file."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(f"{name}.md", md_text)
        archive.writestr(f"{name}_content_list.json", json.dumps(content_items or []))
        for image_name, data in (images or {}).items():
            archive.writestr(f"images/{image_name}", data)
    return buffer.getvalue()


def _install_fake_parse(
    monkeypatch: pytest.MonkeyPatch,
    md_for: Callable[[Path], str] | None = None,
    extras: Callable[[Path], tuple[dict[str, bytes], list]] | None = None,
    record: list | None = None,
) -> list[Path]:
    """Replace the cloud upload/poll/download trio with a fake that records the
    file it was handed and returns a synthetic MinerU archive for it. When
    ``record`` is given, each call appends ``(part_path, page_count)`` — page
    counts must be read at call time because part PDFs live in a temp dir that
    is gone by the time the test asserts."""
    calls: list[Path] = []

    def fake_upload_and_fetch(
        client, part_path: Path, config, key_pool, *, report, poll_interval, timeout
    ) -> bytes:
        calls.append(part_path)
        if record is not None:
            record.append((part_path, len(PdfReader(str(part_path)).pages)))
        images, content_items = extras(part_path) if extras else ({}, [])
        return _fake_archive_bytes(
            part_path.stem,
            md_for(part_path) if md_for else f"# {part_path.stem}",
            images,
            content_items,
        )

    monkeypatch.setattr(mineru_cloud, "_upload_and_fetch_archive", fake_upload_and_fetch)
    return calls


# ---------------------------------------------------------------------------
# Config: max_pages_per_part
# ---------------------------------------------------------------------------


def test_max_pages_per_part_defaults_and_clamps() -> None:
    assert MinerUConfig().max_pages_per_part == 180
    assert MinerUConfig(max_pages_per_part=500).max_pages_per_part == MAX_PAGES_PER_PART_CEILING
    assert MinerUConfig(max_pages_per_part=0).max_pages_per_part == 1


def test_resolve_mineru_config_reads_max_pages_per_part(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        mineru_config,
        "load_mineru_settings",
        lambda: {"mode": "cloud", "api_token": "tok", "max_pages_per_part": 120},
    )
    assert mineru_config.resolve_mineru_config().max_pages_per_part == 120

    monkeypatch.setattr(
        mineru_config, "load_mineru_settings", lambda: {"mode": "cloud", "api_token": "tok"}
    )
    assert mineru_config.resolve_mineru_config().max_pages_per_part == 180


# ---------------------------------------------------------------------------
# Slicing decision
# ---------------------------------------------------------------------------


def test_oversized_pdf_is_sliced_into_180_plus_70(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = _make_pdf(tmp_path / "big.pdf", 250)
    record: list[tuple[Path, int]] = []
    calls = _install_fake_parse(monkeypatch, record=record)
    progress: list[str] = []

    working_dir = mineru_cloud.parse_cloud(
        pdf, tmp_path / "out", CLOUD_CFG, on_progress=progress.append
    )

    assert len(record) == 2
    assert [count for _, count in record] == [180, 70]
    assert calls[0].name == "big_part01.pdf"
    assert calls[1].name == "big_part02.pdf"
    assert working_dir == tmp_path / "out" / "big"
    assert (working_dir / "big.md").is_file()
    assert any("part 1/2" in message for message in progress)
    assert any("part 2/2" in message for message in progress)


def test_small_pdf_uses_original_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pdf = _make_pdf(tmp_path / "small.pdf", 40)
    calls = _install_fake_parse(monkeypatch)
    progress: list[str] = []

    working_dir = mineru_cloud.parse_cloud(
        pdf, tmp_path / "out", CLOUD_CFG, on_progress=progress.append
    )

    # Exactly one parse round-trip, on the original file — no slicing.
    assert len(calls) == 1
    assert calls[0] == pdf
    assert working_dir == tmp_path / "out" / "small"
    assert (working_dir / "small.md").is_file()
    assert not any(marker in message for message in progress for marker in _SLICING_MARKERS)


def test_non_pdf_is_never_sliced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    docx = tmp_path / "notes.docx"
    docx.write_bytes(b"fake docx bytes")
    calls = _install_fake_parse(monkeypatch)
    page_counts = []

    real_page_count = mineru_cloud._pdf_page_count
    monkeypatch.setattr(
        mineru_cloud, "_pdf_page_count", lambda path: page_counts.append(real_page_count(path)) or 0
    )

    working_dir = mineru_cloud.parse_cloud(docx, tmp_path / "out", CLOUD_CFG)

    assert len(calls) == 1
    assert calls[0] == docx
    assert page_counts == []  # the slicer never even counted pages
    assert working_dir == tmp_path / "out" / "notes"


def test_unreadable_pdf_falls_back_to_original_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A PDF pypdf cannot read keeps the legacy single-file behaviour instead of
    failing at the page-count step."""
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.4")  # no EOF marker / no page tree
    calls = _install_fake_parse(monkeypatch)
    progress: list[str] = []

    working_dir = mineru_cloud.parse_cloud(
        broken, tmp_path / "out", CLOUD_CFG, on_progress=progress.append
    )

    assert len(calls) == 1
    assert calls[0] == broken
    assert not any(marker in message for message in progress for marker in _SLICING_MARKERS)
    assert working_dir == tmp_path / "out" / "broken"


# ---------------------------------------------------------------------------
# Merged artifacts
# ---------------------------------------------------------------------------


def test_merged_artifacts_md_order_and_unique_images(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = _make_pdf(tmp_path / "book.pdf", 250)

    part_bodies = {
        "book_part01.pdf": (
            "Alpha intro\n![p1](images/a.jpg)\n![p3](images/b.jpg)\n",
            {"a.jpg": b"one", "b.jpg": b"two"},
        ),
        "book_part02.pdf": ("Beta outro\n![p2](images/a.jpg)\n", {"a.jpg": b"three"}),
    }

    def md_for(part_path: Path) -> str:
        return part_bodies[part_path.name][0]

    def extras(part_path: Path) -> tuple[dict[str, bytes], list]:
        _, images = part_bodies[part_path.name]
        items = [{"type": "image", "img_path": f"images/{name}"} for name in images]
        return images, items

    _install_fake_parse(monkeypatch, md_for=md_for, extras=extras)

    working_dir = mineru_cloud.parse_cloud(pdf, tmp_path / "out", CLOUD_CFG)

    # Markdown is concatenated in part order, no separators.
    merged_md = (working_dir / "book.md").read_text(encoding="utf-8")
    assert merged_md.index("Alpha intro") < merged_md.index("Beta outro")
    assert "Alpha intro" in merged_md and "Beta outro" in merged_md
    assert "book_part01" not in merged_md

    # Every image lands in the merged images/ dir with a globally unique name.
    images_dir = working_dir / "images"
    assert sorted(path.name for path in images_dir.iterdir()) == [
        "part01_a.jpg",
        "part01_b.jpg",
        "part02_a.jpg",
    ]
    assert (images_dir / "part01_a.jpg").read_bytes() == b"one"
    assert (images_dir / "part02_a.jpg").read_bytes() == b"three"

    # Markdown references follow the renamed files (no dangling originals).
    for original in ("images/a.jpg", "images/b.jpg"):
        assert original not in merged_md
    assert "images/part01_a.jpg" in merged_md
    assert "images/part02_a.jpg" in merged_md
    assert "images/part01_b.jpg" in merged_md

    # content_list is merged in part order with rewritten img_path values.
    content_list = json.loads((working_dir / "book_content_list.json").read_text(encoding="utf-8"))
    assert [item["img_path"] for item in content_list] == [
        "images/part01_a.jpg",
        "images/part01_b.jpg",
        "images/part02_a.jpg",
    ]


def test_original_page_indices_include_nested_blocks(tmp_path, monkeypatch):
    pdf = _make_pdf(tmp_path / "book.pdf", 5)
    config = MinerUConfig(mode="cloud", api_token="tok", max_pages_per_part=2)
    _install_fake_parse(
        monkeypatch,
        extras=lambda part: (
            {"a.jpg": b"image"},
            [
                {
                    "type": "image",
                    "img_path": "images/a.jpg",
                    "page_idx": 0,
                    "children": [{"page_idx": 0, "text": "caption"}],
                }
            ],
        ),
    )
    out = mineru_cloud.parse_cloud(pdf, tmp_path / "out", config)
    rows = json.loads((out / "book_content_list.json").read_text())
    assert [row["page_idx"] for row in rows] == [0, 2, 4]
    assert [row["children"][0]["page_idx"] for row in rows] == [0, 2, 4]
    assert all((out / row["img_path"]).is_file() for row in rows)


@pytest.mark.parametrize("bad_index", [-1, 2, True, "0", None, 1.5])
def test_invalid_page_index_does_not_create_ready_checkpoint(tmp_path, monkeypatch, bad_index):
    from deeptutor.services.parsing.engines.mineru.config import MinerUError

    pdf = _make_pdf(tmp_path / "bad.pdf", 3)
    config = MinerUConfig(mode="cloud", api_token="tok", max_pages_per_part=2)
    _install_fake_parse(monkeypatch, extras=lambda part: ({}, [{"page_idx": bad_index}]))
    with pytest.raises(MinerUError, match="page_idx"):
        mineru_cloud.parse_cloud(pdf, tmp_path / "out", config)
    assert not list((tmp_path / "checkpoints").rglob("ready.json"))


def test_retry_reuses_completed_slice_after_output_cleanup(tmp_path, monkeypatch):
    import shutil

    from deeptutor.services.parsing.engines.mineru.config import MinerUError

    pdf = _make_pdf(tmp_path / "retry.pdf", 5)
    config = MinerUConfig(mode="cloud", api_token="tok", max_pages_per_part=2)
    calls = []
    fail = True

    def upload(client, part, config, key_pool, **kwargs):
        calls.append(part.name)
        if fail and part.name.endswith("02.pdf"):
            raise MinerUError("synthetic transport interruption")
        return _fake_archive_bytes(part.stem, "text", content_items=[{"page_idx": 0}])

    monkeypatch.setattr(mineru_cloud, "_upload_and_fetch_archive", upload)
    with pytest.raises(MinerUError, match="interruption"):
        mineru_cloud.parse_cloud(pdf, tmp_path / "out", config)
    shutil.rmtree(tmp_path / "out")  # ParseService removes failed work directories
    fail = False
    out = mineru_cloud.parse_cloud(pdf, tmp_path / "out", config)
    assert calls == ["retry_part01.pdf", "retry_part02.pdf", "retry_part02.pdf", "retry_part03.pdf"]
    assert [
        row["page_idx"] for row in json.loads((out / "retry_content_list.json").read_text())
    ] == [0, 2, 4]


def test_corrupt_checkpoint_reparses_only_affected_slice(tmp_path, monkeypatch):
    pdf = _make_pdf(tmp_path / "book.pdf", 3)
    config = MinerUConfig(mode="cloud", api_token="tok", max_pages_per_part=2)
    calls = _install_fake_parse(monkeypatch)
    mineru_cloud.parse_cloud(pdf, tmp_path / "out", config)
    archive = next((tmp_path / "checkpoints").glob("*/0-2/*.zip"))
    archive.write_bytes(b"truncated")
    calls.clear()
    mineru_cloud.parse_cloud(pdf, tmp_path / "out", config)
    assert [p.name for p in calls] == ["book_part01.pdf"]


def test_checkpoint_identity_tracks_source_and_parser_but_not_credentials(tmp_path):
    from dataclasses import replace

    from deeptutor.services.parsing.engines.mineru.checkpoints import job_directory

    pdf = _make_pdf(tmp_path / "book.pdf", 3)
    config = MinerUConfig(mode="cloud", api_token="secret-one", max_pages_per_part=2)
    key = job_directory(pdf, config)
    assert job_directory(pdf, replace(config, api_token="secret-two")) == key
    for change in [
        dict(language="ch"),
        dict(model_version="vlm"),
        dict(is_ocr=True),
        dict(enable_formula=False),
        dict(enable_table=False),
        dict(max_pages_per_part=1),
        dict(api_base_url="https://example.test"),
    ]:
        assert job_directory(pdf, replace(config, **change)) != key
    _make_pdf(pdf, 4)
    assert job_directory(pdf, config) != key


def test_slice_setting_persists_and_cloud_signature_changes(tmp_path):
    from deeptutor.services.config.runtime_settings import RuntimeSettingsService
    from deeptutor.services.parsing.engines.mineru.engine import MinerUParser

    service = RuntimeSettingsService(tmp_path / "settings", process_env={})
    service.save_mineru({"max_pages_per_part": 120})
    assert service.load_mineru()["max_pages_per_part"] == 120
    service.save_mineru({"max_pages_per_part": 500})
    assert service.load_mineru()["max_pages_per_part"] == 200
    parser = MinerUParser()
    assert parser.signature(MinerUConfig(mode="cloud", max_pages_per_part=2)) != parser.signature(
        MinerUConfig(mode="cloud", max_pages_per_part=3)
    )
    assert parser.signature(MinerUConfig(mode="local", max_pages_per_part=2)) == parser.signature(
        MinerUConfig(mode="local", max_pages_per_part=3)
    )


def test_default_180_page_boundary_is_rebased(tmp_path, monkeypatch):
    pdf = _make_pdf(tmp_path / "large.pdf", 181)
    _install_fake_parse(monkeypatch, extras=lambda part: ({}, [{"page_idx": 0}]))
    out = mineru_cloud.parse_cloud(pdf, tmp_path / "out", CLOUD_CFG)
    rows = json.loads((out / "large_content_list.json").read_text())
    assert [row["page_idx"] for row in rows] == [0, 180]


def test_checkpoint_write_failure_does_not_fail_parse(tmp_path, monkeypatch):
    from deeptutor.services.parsing.engines.mineru.checkpoints import SliceCheckpoint

    def fail_save(self, archive):
        raise OSError("synthetic read-only cache")

    monkeypatch.setattr(SliceCheckpoint, "save", fail_save)
    pdf = _make_pdf(tmp_path / "book.pdf", 3)
    config = MinerUConfig(mode="cloud", api_token="tok", max_pages_per_part=2)
    _install_fake_parse(monkeypatch)
    out = mineru_cloud.parse_cloud(pdf, tmp_path / "out", config)
    assert (out / "book.md").is_file()


@pytest.mark.parametrize("pointer", ["{", "[]", '{"sha256":"../../escape"}'])
def test_invalid_checkpoint_pointer_is_a_miss(tmp_path, pointer):
    from deeptutor.services.parsing.engines.mineru.checkpoints import SliceCheckpoint

    checkpoint = SliceCheckpoint(tmp_path, 0, 2)
    checkpoint.directory.mkdir()
    checkpoint.pointer.write_text(pointer)
    assert checkpoint.load() is None
