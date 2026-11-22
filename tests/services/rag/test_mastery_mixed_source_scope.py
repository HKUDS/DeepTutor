"""Regression tests for #2859.

A Mastery Path objective that selects both PDF and Markdown materials builds a
PDF-only evidence scope. That restriction is deliberate — questions are verified
against rendered original pages — but the failures used to blame the question,
leaving the reader unable to tell a bad question from a source that was never in
the evidence chain.

These tests pin the two halves of the fix:

* the scope builder reports what it skipped (purely diagnostic);
* the messages that fire name those materials.

The security property is unchanged and is asserted here too: a skipped source
still cannot authorize anything.
"""

from __future__ import annotations

import contextlib
from types import SimpleNamespace

import pytest

from deeptutor.learning import lesson_evidence as lessons
from deeptutor.learning.lesson_evidence import (
    describe_skipped,
    selected_scope,
    validate_evidence,
)
from deeptutor.learning.models import (
    KnowledgePoint,
    LearningModule,
    LearningProgress,
    TopicSource,
    TopicSourceKind,
)


def _progress() -> LearningProgress:
    return LearningProgress(
        book_id="path",
        modules=[
            LearningModule(
                id="m",
                name="Cells",
                order=0,
                knowledge_points=[
                    KnowledgePoint(
                        id="kp",
                        name="Membranes",
                        type="memory",
                        module_id="m",
                        topic_source_ids=["pdf-kb", "md-kb"],
                    )
                ],
            )
        ],
    )


def _sources() -> list[TopicSource]:
    return [
        TopicSource(
            id="pdf-kb",
            kind=TopicSourceKind.KNOWLEDGE_BASE,
            label="Reference papers",
            source_id="pdf-kb",
        ),
        TopicSource(
            id="md-kb",
            kind=TopicSourceKind.KNOWLEDGE_BASE,
            label="Beginner guide",
            source_id="md-kb",
        ),
    ]


def _topic() -> SimpleNamespace:
    """A topic carrying both sources.

    ``TopicMetadata`` itself has no ``sources`` field — the store keeps the pair
    together — and ``selected_scope`` only reads ``.sources``, so a namespace is
    the honest stand-in here.
    """
    return SimpleNamespace(sources=_sources())


@pytest.fixture
def kbs(tmp_path, monkeypatch):
    """Two KBs on disk: one with a PDF, one Markdown only."""
    pdf_raw = tmp_path / "pdf-kb" / "raw"
    pdf_raw.mkdir(parents=True)
    (pdf_raw / "paper.pdf").write_bytes(b"%PDF-1.4 placeholder")
    md_raw = tmp_path / "md-kb" / "raw"
    md_raw.mkdir(parents=True)
    (md_raw / "guide.md").write_text("# Beginner guide\n", encoding="utf-8")

    def fake_resolve(kb):
        base = tmp_path / kb
        return SimpleNamespace(base_dir=base.parent, name=kb) if base.is_dir() else None

    monkeypatch.setattr("deeptutor.multi_user.knowledge_access.resolve_for_rag", fake_resolve)
    monkeypatch.setattr(
        "deeptutor.services.workspace.knowledge.learning_source_access",
        lambda *args, **kwargs: contextlib.nullcontext(),
    )
    return tmp_path


def test_scope_reports_the_markdown_source_it_skips(kbs) -> None:
    """The skipped label is what lets an error message explain itself."""
    skipped: list[str] = []

    scope = selected_scope(_topic(), _progress(), "kp", skipped=skipped)

    # Unchanged behaviour: only the PDF-bearing KB is in scope.
    assert scope == {"pdf-kb": None}
    # New: the exclusion is visible.
    assert skipped == ["Beginner guide"]


def test_scope_stays_silent_when_every_source_has_pdf(kbs) -> None:
    (kbs / "md-kb" / "raw" / "also.pdf").write_bytes(b"%PDF-1.4")
    skipped: list[str] = []

    scope = selected_scope(_topic(), _progress(), "kp", skipped=skipped)

    assert scope == {"pdf-kb": None, "md-kb": None}
    assert skipped == []


def test_skip_reporting_does_not_widen_the_scope(kbs) -> None:
    """Diagnostics must never make an out-of-scope source authorizable."""
    skipped: list[str] = []

    scope = selected_scope(_topic(), _progress(), "kp", skipped=skipped)

    assert skipped, "the fixture must skip something for this test to mean anything"
    assert "md-kb" not in scope


def test_scope_without_the_output_list_still_works(kbs) -> None:
    """The parameter is optional: existing callers keep their signature."""
    assert selected_scope(_topic(), _progress(), "kp") == {"pdf-kb": None}


def test_validate_evidence_names_the_skipped_material(kbs) -> None:
    """The old message claimed the PDF materials changed; now it explains why."""
    progress = _progress()
    topic = _topic()
    store = SimpleNamespace(
        get_topic=lambda _book, progress=None: topic,
        load=lambda _path: progress,
    )
    evidence = {"status": "ready", "schema_version": lessons.SCHEMA, "sources": []}

    # Remove the only PDF source so the scope comes out empty while selected
    # materials remain — exactly the mixed-topic shape.
    (kbs / "pdf-kb" / "raw" / "paper.pdf").unlink()

    with pytest.raises(lessons.LessonUnavailable) as excinfo:
        validate_evidence(store, progress, "kp", evidence)

    message = str(excinfo.value)
    assert "changed" in message
    assert "Beginner guide" in message
    assert "no PDF pages" in message


def test_validate_evidence_still_passes_without_pdf_scope(kbs) -> None:
    """No PDF material and no evidence is the text-tutoring path, not a failure."""
    progress = _progress()
    store = SimpleNamespace(
        get_topic=lambda _book, progress=None: _topic(),
        load=lambda _path: progress,
    )
    (kbs / "pdf-kb" / "raw" / "paper.pdf").unlink()

    validate_evidence(store, progress, "kp", {})


def test_validate_evidence_fills_the_callers_skipped_list(kbs) -> None:
    """``skipped`` is an output parameter: the caller's list must receive data.

    It was once shadowed by a local list, so ``bind_questions`` collected
    nothing and its failure message silently lost the explanation.
    """
    progress = _progress()
    store = SimpleNamespace(
        get_topic=lambda _book, progress=None: _topic(),
        load=lambda _path: progress,
    )
    skipped: list[str] = []
    evidence = {"status": "ready", "schema_version": lessons.SCHEMA, "sources": []}

    # Any failure past the scope check is fine here; the point is that the
    # caller's list was populated on the way.
    with pytest.raises(lessons.LessonUnavailable):
        validate_evidence(store, progress, "kp", evidence, skipped=skipped)

    assert skipped == ["Beginner guide"]


def test_describe_skipped_is_empty_without_skips() -> None:
    """Callers append unconditionally, so no skips must mean no sentence."""
    assert describe_skipped([]) == ""


def test_describe_skipped_lists_labels_and_truncates() -> None:
    single = describe_skipped(["Guide"])
    assert "Guide" in single

    many = describe_skipped(["A", "B", "C", "D"])
    assert "A" in many and "and others" in many
    assert "\u201cD\u201d" not in many, "the fourth label should be truncated away"


def test_describe_skipped_agrees_grammatically() -> None:
    assert "materials has no PDF pages" in describe_skipped(["One"])
    assert "materials have no PDF pages" in describe_skipped(["One", "Two"])
