"""Book creation must persist one concrete language for every later stage."""

from __future__ import annotations

import pytest

from deeptutor.book.engine import BookEngine
from deeptutor.book.models import BookInputs, BookProposal


class _RecordingStorage:
    def __init__(self) -> None:
        self.books: list = []
        self.inputs: list[BookInputs] = []

    def save_book(self, book) -> None:
        self.books.append(book)

    def save_inputs(self, book_id: str, inputs: BookInputs) -> None:
        self.inputs.append(inputs)

    def save_progress(self, progress) -> None:
        self.progress = progress

    def append_log(self, *args, **kwargs) -> None:
        self.log_calls = (args, kwargs)


@pytest.mark.asyncio
async def test_create_book_resolves_auto_before_inputs_are_persisted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = object.__new__(BookEngine)
    engine.storage = _RecordingStorage()

    async def fake_ideation(self, ctx, language: str) -> BookProposal:
        return BookProposal(title="Language Test", estimated_chapters=1)

    monkeypatch.setattr(BookEngine, "_run_ideation", fake_ideation)

    book, _proposal = await engine.create_book(
        user_intent="Please make a Fourier book in Japanese",
        language="auto",
        fallback_language="zh",
    )

    assert book.language == "ja"
    assert engine.storage.inputs[0].language == "ja"
