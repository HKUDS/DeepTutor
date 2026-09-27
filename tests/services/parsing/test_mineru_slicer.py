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
