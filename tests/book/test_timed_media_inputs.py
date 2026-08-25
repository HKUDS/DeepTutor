from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.book.agents.source_explorer import SourceExplorer
from deeptutor.book.inputs import build_book_inputs
from deeptutor.book.models import BookInputs
from deeptutor.video_learning.marks import create_mark
from deeptutor.video_learning.service import TimedMediaStore


def _material(store: TimedMediaStore) -> dict:
    material = store.create(
        {
            "type": "timed_media",
            "source": {
                "provider": "youtube",
                "video_id": "abcdef12345",
                "url": "https://youtu.be/abcdef12345",
                "duration_seconds": 90,
            },
            "metadata": {
                "title": "Fourier Basics",
                "author": "Tutor",
                "duration_seconds": 90,
                "chapters": [],
            },
            "transcript": {
                "language": "en",
                "source": "invidious",
                "cues": [{"start": 5, "end": 12, "text": "A Fourier series decomposes periodic signals."}],
            },
            "segments": [
                {
                    "locator": 1,
                    "start": 5,
                    "end": 12,
                    "text": "A Fourier series decomposes periodic signals.",
                }
            ],
            "playback": {"formats": {}, "official_url": "https://youtu.be/abcdef12345"},
            "learning": {"last_position": 0, "notes": [], "marks": []},
        }
    )
    create_mark(
        material,
        {
            "kind": "key_point",
            "start_seconds": 5,
            "end_seconds": 12,
            "quote": "A Fourier series decomposes periodic signals.",
        },
    )
    store.save(material)
    return store.get(material["material_id"])


@pytest.mark.asyncio
async def test_build_book_inputs_includes_timed_media(tmp_path: Path, monkeypatch):
    store = TimedMediaStore(tmp_path / "timed_media")
    material = _material(store)
    monkeypatch.setattr("deeptutor.video_learning.service.get_timed_media_store", lambda: store)

    book_inputs, ideation = await build_book_inputs(
        user_intent="Make a learning book from this video",
        timed_media_ids=[material["material_id"]],
        language="en",
    )
    assert book_inputs.timed_media_ids == [material["material_id"]]
    assert "Fourier Basics" in book_inputs.video_learning_text
    assert ideation.timed_media_count == 1
    assert "Fourier Basics" in ideation.render()


def test_source_explorer_collects_timed_media_chunks(tmp_path: Path, monkeypatch):
    store = TimedMediaStore(tmp_path / "timed_media")
    material = _material(store)
    monkeypatch.setattr("deeptutor.video_learning.service.get_timed_media_store", lambda: store)

    explorer = SourceExplorer(language="en")
    inputs = BookInputs(
        user_intent="video book",
        timed_media_ids=[material["material_id"]],
        video_learning_text="unused for this unit",
    )
    chunks = explorer._collect_non_kb_chunks(inputs)
    timed = [c for c in chunks if c.source == "timed_media"]
    assert timed
    assert timed[0].metadata.get("material_id") == material["material_id"]
    assert timed[0].metadata.get("jump_url", "").startswith("/home?watching_material=")
