"""Quiz reads QuestionPipeline's result directly, not the legacy summary shape.

`AgentCoordinator` is a documented legacy facade; going through it also built a
throwaway StreamBus, so progress from the book's slowest block was discarded.
Reading the pipeline directly means the extraction has to apply the `success`
rule the facade used to back-fill.
"""

from __future__ import annotations

from deeptutor.book.blocks.quiz import QuizGenerator


def _qa(qid: str) -> dict:
    return {
        "question_id": qid,
        "question": f"Q{qid}?",
        "question_type": "single_choice",
        "options": {"a": "1", "b": "2"},
        "correct_answer": "A",
        "explanation": "because",
    }


def test_explicit_success_flags_are_honoured() -> None:
    summary = {
        "results": [
            {"success": True, "qa_pair": _qa("1")},
            {"success": False, "qa_pair": _qa("2")},
        ]
    }
    got = QuizGenerator._extract_questions(summary)
    assert [q["question_id"] for q in got] == ["1"]


def test_missing_success_falls_back_to_the_error_marker() -> None:
    """The pipeline's native shape has no `success` key — the facade added it."""
    summary = {
        "results": [
            {"qa_pair": _qa("1"), "metadata": {}},
            {"qa_pair": _qa("2"), "metadata": {"error": "generation failed"}},
            {"qa_pair": _qa("3")},  # no metadata at all → keep
        ]
    }
    got = QuizGenerator._extract_questions(summary)
    assert [q["question_id"] for q in got] == ["1", "3"]


def test_malformed_entries_are_skipped_not_crashed() -> None:
    summary = {"results": ["nonsense", None, 42, {"qa_pair": "not a dict"}]}
    assert QuizGenerator._extract_questions(summary) == []


def test_an_empty_or_absent_result_set_yields_nothing() -> None:
    assert QuizGenerator._extract_questions({}) == []
    assert QuizGenerator._extract_questions({"results": []}) == []
    assert QuizGenerator._extract_questions({"results": "not a list"}) == []


def test_the_question_shape_is_preserved() -> None:
    got = QuizGenerator._extract_questions({"results": [{"success": True, "qa_pair": _qa("7")}]})
    assert got[0]["question"] == "Q7?"
    assert got[0]["question_type"] == "single_choice"
    assert got[0]["options"] == {"a": "1", "b": "2"}


def test_the_legacy_facade_is_no_longer_imported() -> None:
    """The name may still appear in a comment; what matters is the import."""
    import ast
    import inspect

    import deeptutor.book.blocks.quiz as module

    imported: set[str] = set()
    for node in ast.walk(ast.parse(inspect.getsource(module))):
        if isinstance(node, ast.ImportFrom):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)

    assert "AgentCoordinator" not in imported
    assert "QuestionPipeline" in imported


# ── Call contract ───────────────────────────────────────────────────────
#
# Quiz calls QuestionPipeline directly now, so a signature change upstream
# would only surface when a reader actually generates a quiz. These pin the
# contract at import time instead.


def test_the_pipeline_call_is_signature_correct() -> None:
    import inspect

    from deeptutor.agents.question.pipeline import QuestionPipeline

    run = inspect.signature(QuestionPipeline.run)
    accepted = set(run.parameters) - {"self"}
    passed = {
        "context",
        "user_message",
        "num_questions",
        "difficulty",
        "question_types",
        "stream",
    }
    assert passed <= accepted, f"quiz passes unknown args: {passed - accepted}"

    required = {
        name
        for name, p in run.parameters.items()
        if name != "self"
        and p.default is inspect.Parameter.empty
        and p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)
    }
    assert required <= passed, f"quiz omits required args: {required - passed}"


def test_the_pipeline_constructor_accepts_what_quiz_passes() -> None:
    import inspect

    from deeptutor.agents.question.pipeline import QuestionPipeline

    ctor = set(inspect.signature(QuestionPipeline.__init__).parameters) - {"self"}
    assert {"language", "kb_name"} <= ctor


def test_the_context_fields_quiz_sets_all_exist() -> None:
    import inspect

    from deeptutor.core.context import UnifiedContext

    fields = set(inspect.signature(UnifiedContext.__init__).parameters) - {"self"}
    mine = {
        "session_id",
        "user_message",
        "active_capability",
        "knowledge_bases",
        "language",
    }
    assert mine <= fields, f"unknown UnifiedContext fields: {mine - fields}"


def test_progress_reaches_the_books_own_stream() -> None:
    """The reason for going direct: the facade discarded the stream."""
    import inspect

    import deeptutor.book.blocks.quiz as module

    source = inspect.getsource(module)
    assert "get_book_bus(ctx.book_id)" in source, (
        "quiz must publish into the book's long-lived bus, not a throwaway one"
    )
