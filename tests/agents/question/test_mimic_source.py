from __future__ import annotations

import json
from pathlib import Path

from deeptutor.agents.question.mimic_source import (
    _coerce_difficulty,
    _coerce_question_type,
    _parse_sync,
)


def test_coerce_question_type_maps_to_canonical_taxonomy() -> None:
    assert _coerce_question_type("CHOICE") == "choice"
    assert _coerce_question_type("coding") == "coding"
    assert _coerce_question_type("fill_in_blank") == "fill_in_blank"
    # Anything off-taxonomy degrades to a free-text written question.
    assert _coerce_question_type("nonsense") == "written"
    assert _coerce_question_type(None) == "written"
    assert _coerce_question_type("") == "written"


def test_coerce_difficulty_validates_levels() -> None:
    assert _coerce_difficulty("Hard") == "hard"
    assert _coerce_difficulty("easy") == "easy"
    assert _coerce_difficulty("") == "medium"
    assert _coerce_difficulty("trivial") == "medium"
    assert _coerce_difficulty(None) == "medium"


def test_parse_sync_maps_extracted_type_difficulty_and_answer(tmp_path: Path) -> None:
    # "parsed" mode with a pre-existing *_questions.json skips MinerU + the LLM
    # extractor entirely, so this is a pure mapping test.
    paper = tmp_path / "exam"
    paper.mkdir()
    (paper / "exam_questions.json").write_text(
        json.dumps(
            {
                "questions": [
                    {
                        "question_number": "1",
                        "question_text": "Which is correct?\nA. a\nB. b\nC. c\nD. d",
                        "question_type": "choice",
                        "difficulty": "easy",
                        "answer": "B",
                    },
                    {
                        "question_number": "2",
                        "question_text": "Explain backpropagation.",
                        "question_type": "WeirdType",  # invalid → written
                        "difficulty": "impossible",  # invalid → medium
                        "answer": "",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    templates, trace = _parse_sync(paper, 10, "parsed", tmp_path / "out")

    assert len(templates) == 2
    first, second = templates

    assert first.question_type == "choice"
    assert first.difficulty == "easy"
    assert first.reference_answer == "B"
    assert first.source == "mimic"
    assert first.reference_question.startswith("Which is correct?")

    # Off-taxonomy values fall back to safe defaults.
    assert second.question_type == "written"
    assert second.difficulty == "medium"
    assert second.reference_answer is None

    assert trace["template_count"] == "2"


def test_parse_sync_respects_max_questions(tmp_path: Path) -> None:
    paper = tmp_path / "exam"
    paper.mkdir()
    (paper / "exam_questions.json").write_text(
        json.dumps(
            {
                "questions": [
                    {"question_text": f"Q{i}", "question_type": "short_answer"} for i in range(5)
                ]
            }
        ),
        encoding="utf-8",
    )

    templates, _ = _parse_sync(paper, 2, "parsed", tmp_path / "out")
    assert len(templates) == 2


def test_parse_sync_upload_mode_uses_parse_service_and_isolates_output(
    tmp_path: Path, monkeypatch
) -> None:
    """Upload mode goes through the shared ParseService and writes the
    questions JSON to the session output dir, never the shared parse cache."""
    from deeptutor.agents.question import mimic_source
    from deeptutor.services.parsing.types import ParsedDocument

    # The parse cache dir the (fake) ParseService returns as the parsed workdir.
    cache_dir = tmp_path / "parse_cache" / "abc"
    cache_dir.mkdir(parents=True)
    (cache_dir / "exam.md").write_text("# parsed", encoding="utf-8")

    class _FakeService:
        def parse(self, source_path, **kwargs):
            return ParsedDocument(
                markdown="# parsed", workdir=cache_dir, engine="fake", source_hash="h"
            )

    monkeypatch.setattr(mimic_source, "get_parse_service", lambda: _FakeService())

    captured: dict = {}

    def _fake_extract(paper_dir, output_dir=None):
        captured["paper_dir"] = paper_dir
        captured["output_dir"] = output_dir
        # Mimic the real extractor: write the questions JSON to output_dir.
        out = Path(output_dir)
        (out / "exam_questions.json").write_text(
            json.dumps({"questions": [{"question_text": "Q1", "question_type": "written"}]}),
            encoding="utf-8",
        )
        return True

    monkeypatch.setattr(mimic_source, "extract_questions_from_paper", _fake_extract)

    output_base = tmp_path / "session-out"
    pdf = tmp_path / "exam.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    templates, trace = _parse_sync(pdf, 10, "upload", output_base)

    assert len(templates) == 1
    # Parsed content is read from the cache workdir...
    assert captured["paper_dir"] == str(cache_dir)
    # ...but the questions JSON is written to the session dir, not the cache.
    assert captured["output_dir"] == str(output_base)
    assert (output_base / "exam_questions.json").exists()
    assert not (cache_dir / "exam_questions.json").exists()
