"""Tests for vision-model image captions on reading materials.

The vision client is stubbed so no network call is made; the store, the media
index round-trip and the refresh guard are exercised for real on a tmp store.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
import random

from PIL import Image as PILImage
import pytest

from deeptutor.reading import captions as captions_module
from deeptutor.reading.models import ReadingError
from deeptutor.reading.store import ReadingStore

_MATERIAL_ID = "a" * 16


class _StubClient:
    """Minimal stand-in for the LLM facade used by the caption pass."""

    def __init__(self, *, vision: bool = True, fail: set[str] | None = None) -> None:
        self._vision = vision
        self._fail = fail or set()
        self.calls: list[str] = []

    def supports_multimodal_images(self) -> bool:
        return self._vision

    async def complete(
        self, prompt: str, system_prompt: str | None = None, **kwargs: object
    ) -> str:
        name = str(kwargs.get("image_filename") or "")
        self.calls.append(name)
        if name in self._fail:
            raise RuntimeError("vision call failed")
        return f"a chart labelled {name}"


@pytest.fixture(autouse=True)
def _fast_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(captions_module, "image_description_limits", lambda: (4, 5.0))


@pytest.fixture
def store(tmp_path: Path) -> ReadingStore:
    root = tmp_path / "reading"
    root.mkdir()
    store = ReadingStore(root)
    store.ingest_units(
        _MATERIAL_ID,
        filename="deck.pptx",
        unit="slide",
        units=["Slide one text", "Slide two text"],
    )
    media_dir = root / _MATERIAL_ID / "media"
    media_dir.mkdir()
    rows = []
    for index in range(3):
        name = f"image-{index:02d}.png"
        (media_dir / name).write_bytes(b"png-bytes")
        rows.append({"name": name, "locator": 1, "mime": "image/png", "bytes": 9})
    (root / _MATERIAL_ID / "media.json").write_text(json.dumps(rows), encoding="utf-8")
    return store


@pytest.mark.asyncio
async def test_caption_material_media_writes_back(
    store: ReadingStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub = _StubClient()
    monkeypatch.setattr(captions_module, "get_llm_client", lambda: stub)

    written = await captions_module.caption_material_media(_MATERIAL_ID, store=store)

    assert written == 3
    assert len(stub.calls) == 3
    rows = store.media_items(_MATERIAL_ID)
    assert all(str(row.get("caption") or "") for row in rows)


@pytest.mark.asyncio
async def test_existing_captions_are_skipped(
    store: ReadingStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub = _StubClient()
    monkeypatch.setattr(captions_module, "get_llm_client", lambda: stub)

    assert await captions_module.caption_material_media(_MATERIAL_ID, store=store) == 3
    stub.calls.clear()

    again = await captions_module.caption_material_media(_MATERIAL_ID, store=store)

    assert again == 0
    assert stub.calls == []


@pytest.mark.asyncio
async def test_single_failure_keeps_the_rest(
    store: ReadingStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub = _StubClient(fail={"image-01.png"})
    monkeypatch.setattr(captions_module, "get_llm_client", lambda: stub)

    written = await captions_module.caption_material_media(_MATERIAL_ID, store=store)

    assert written == 2
    captions = {row["name"]: row.get("caption") for row in store.media_items(_MATERIAL_ID)}
    assert captions["image-00.png"]
    assert captions["image-02.png"]
    assert not captions.get("image-01.png")


@pytest.mark.asyncio
async def test_text_only_client_makes_no_calls(
    store: ReadingStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub = _StubClient(vision=False)
    monkeypatch.setattr(captions_module, "get_llm_client", lambda: stub)

    written = await captions_module.caption_material_media(_MATERIAL_ID, store=store)

    assert written == 0
    assert stub.calls == []


def test_update_media_captions_ignores_unknown_names(store: ReadingStore) -> None:
    changed = store.update_media_captions(
        _MATERIAL_ID, {"missing.png": "ghost", "image-00.png": "hello"}
    )

    assert changed == 1
    captions = {row["name"]: row.get("caption") for row in store.media_items(_MATERIAL_ID)}
    assert captions["image-00.png"] == "hello"
    assert not captions.get("image-01.png")
    # An empty value never erases an existing caption nor counts as a change.
    assert store.update_media_captions(_MATERIAL_ID, {"image-01.png": ""}) == 0


# ---------------------------------------------------------------------------
# refresh_document
# ---------------------------------------------------------------------------


def _png_bytes(seed: int = 11) -> bytes:
    rng = random.Random(seed)
    data = bytes(rng.randrange(256) for _ in range(400 * 300 * 3))
    buf = io.BytesIO()
    PILImage.frombytes("RGB", (400, 300), data).save(buf, format="PNG")
    return buf.getvalue()


def _pdf_with_image(path: Path) -> None:
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    prose = "Figure one shows the measured throughput across three configurations. " * 8
    page.insert_textbox(pymupdf.Rect(72, 72, 520, 280), prose, fontsize=9)
    page.insert_image(pymupdf.Rect(72, 320, 300, 520), stream=_png_bytes(seed=11))
    page.insert_image(pymupdf.Rect(320, 320, 540, 520), stream=_png_bytes(seed=23))
    doc.save(str(path))
    doc.close()


def test_refresh_document_preserves_state_and_captions(tmp_path: Path) -> None:
    store = ReadingStore(tmp_path / "reading")
    pdf = tmp_path / "deck.pdf"
    _pdf_with_image(pdf)
    manifest = store.ingest(pdf)
    names = [str(row["name"]) for row in store.media_items(manifest.material_id)]
    assert manifest.unit_count >= 1
    assert len(names) >= 2  # one figure kept, one re-appearing uncaptioned

    content_dir = tmp_path / "reading" / manifest.material_id
    annotation_file = content_dir / "annotations" / f"{manifest.material_id}.json"
    annotation_file.parent.mkdir(parents=True, exist_ok=True)
    annotation_file.write_text("[]", encoding="utf-8")
    position_file = content_dir / "positions" / f"{manifest.material_id}.json"
    position_file.parent.mkdir(parents=True, exist_ok=True)
    position_file.write_text("{}", encoding="utf-8")

    # Generated rasters must survive a re-extraction untouched.
    asset_file = content_dir / "assets" / "cover.png"
    asset_file.parent.mkdir(parents=True, exist_ok=True)
    asset_file.write_bytes(b"poster-bytes")

    # The same image gets a different old filename, while the other old
    # filename now holds different bytes. Only the matching image may keep
    # its caption when extraction assigns ordinal names again.
    kept_name = names[0]
    new_name = names[1]
    legacy_name = "legacy-figure.png"
    media_dir = content_dir / "media"
    (media_dir / kept_name).rename(media_dir / legacy_name)
    (media_dir / new_name).write_bytes(_png_bytes(seed=77))
    media_index = content_dir / "media.json"
    rows = [
        {
            "name": legacy_name,
            "locator": 1,
            "mime": "image/png",
            "bytes": 9,
            "caption": f"kept caption for {kept_name}",
        },
        {
            "name": new_name,
            "locator": 1,
            "mime": "image/png",
            "bytes": 9,
            "caption": "stale caption for replaced bytes",
        },
    ]
    rows.append(
        {
            "name": "ghost.png",
            "locator": 1,
            "mime": "image/png",
            "bytes": 9,
            "caption": "ghost caption",
        }
    )
    media_index.write_text(json.dumps(rows), encoding="utf-8")

    refreshed = store.refresh_document(manifest.material_id)

    assert refreshed.unit_count == manifest.unit_count
    assert refreshed.revision == manifest.revision + 1
    assert annotation_file.is_file()
    assert position_file.is_file()
    assert asset_file.read_bytes() == b"poster-bytes"
    captions = {row["name"]: row.get("caption") for row in store.media_items(manifest.material_id)}
    assert captions.get(kept_name) == f"kept caption for {kept_name}"
    assert new_name in captions and not captions.get(new_name)
    assert "ghost.png" not in captions
    assert legacy_name not in captions


def test_refresh_document_requires_raw_bytes(tmp_path: Path) -> None:
    store = ReadingStore(tmp_path / "reading")
    store.ingest_units("b" * 16, filename="notes.txt", units=["Some notes"])

    with pytest.raises(ReadingError):
        store.refresh_document("b" * 16)

    assert store.unit_text("b" * 16, 1) == "Some notes"
