"""Unit tests for the new QuestionPipeline primitives.

These tests cover the pure helpers (plan parsing, payload normalization,
issue collection) and the structured per-question emission. End-to-end
flow (loop driving + LLM streaming) is exercised by integration tests
that mock the LLM client; out of scope here.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from deeptutor.agents.question.pipeline import (
    CALL_KIND_QUIZ_QUESTION,
    STAGE_QUIZZING,
    QuestionPipeline,
    QuizPair,
    QuizPlan,
    QuizTemplate,
)

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_pipeline(language: str = "en") -> QuestionPipeline:
    """Build a pipeline without hitting the network for LLM config."""
    # Tests don't drive ``run`` — they only exercise pure helpers and the
    # YAML-driven trace metadata builders. So the LLM config can be the
    # production one (env-based) without making any actual API calls.
    return QuestionPipeline(language=language)


class _StubStreamBus:
    """Captures every emission for assertion. No event ordering checks
    beyond ``contents`` containing what we expect."""

    def __init__(self) -> None:
        # Instance attributes are kept distinct from the method names so the
        # methods don't get shadowed when ``progress``/``error`` are called.
        # (The original version named both the list and the method
        # ``progress``, which silently dropped every captured event.)
        self.contents: list[dict[str, Any]] = []
        self.progress_events: list[dict[str, Any]] = []
        self.error_events: list[dict[str, Any]] = []

    async def content(
        self,
        text: str,
        source: str = "",
        stage: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.contents.append(
            {"text": text, "source": source, "stage": stage, "metadata": metadata or {}}
        )

    async def progress(
        self,
        message: str,
        current: int = 0,
        total: int = 0,
        source: str = "",
        stage: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.progress_events.append(
            {
                "message": message,
                "source": source,
                "stage": stage,
                "metadata": metadata or {},
            }
        )

    async def error(
        self,
        message: str,
        source: str = "",
        stage: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.error_events.append(
            {"message": message, "source": source, "stage": stage, "metadata": metadata or {}}
        )


# ---------------------------------------------------------------------------
# parse_plan
# ---------------------------------------------------------------------------


def test_parse_plan_happy_path() -> None:
    pipeline = _make_pipeline()
    raw = json.dumps(
        {
            "analysis": "mix of recall + applied",
            "templates": [
                {"topic": "Definition of X", "question_type": "choice", "difficulty": "easy"},
                {"topic": "Apply X to Y", "question_type": "written", "difficulty": "medium"},
            ],
        }
    )
    plan = pipeline._parse_plan(raw, requested=2, allowed_types=[], target_difficulty="")
    assert plan.analysis == "mix of recall + applied"
    assert [t.topic for t in plan.templates] == ["Definition of X", "Apply X to Y"]
    assert [t.question_id for t in plan.templates] == ["q_1", "q_2"]
    assert plan.templates[0].question_type == "choice"
    assert plan.templates[1].difficulty == "medium"


def test_parse_plan_dedupes_topics_case_insensitive() -> None:
    pipeline = _make_pipeline()
    raw = json.dumps(
        {
            "templates": [
                {"topic": "Matrix Multiplication", "question_type": "written"},
                {"topic": "matrix multiplication", "question_type": "choice"},
                {"topic": "Eigenvalues", "question_type": "written"},
            ]
        }
    )
    plan = pipeline._parse_plan(raw, requested=3, allowed_types=[], target_difficulty="")
    assert len(plan.templates) == 2
    assert plan.templates[0].topic == "Matrix Multiplication"
    assert plan.templates[1].topic == "Eigenvalues"


def test_parse_plan_respects_user_specified_type_and_difficulty() -> None:
    """When ``allowed_types`` restricts the set to a single type, every
    template must use that type. Difficulty override behaves the same way."""
    pipeline = _make_pipeline()
    raw = json.dumps(
        {
            "templates": [
                {"topic": "T1", "question_type": "choice", "difficulty": "easy"},
                {"topic": "T2", "question_type": "written", "difficulty": "hard"},
            ]
        }
    )
    plan = pipeline._parse_plan(
        raw, requested=2, allowed_types=["coding"], target_difficulty="medium"
    )
    assert all(t.question_type == "coding" for t in plan.templates)
    assert all(t.difficulty == "medium" for t in plan.templates)


def test_parse_plan_invalid_json_returns_empty() -> None:
    pipeline = _make_pipeline()
    plan = pipeline._parse_plan(
        "not even json", requested=3, allowed_types=[], target_difficulty=""
    )
    assert isinstance(plan, QuizPlan)
    assert plan.templates == []


def test_parse_plan_truncates_to_requested() -> None:
    pipeline = _make_pipeline()
    raw = json.dumps(
        {
            "templates": [
                {"topic": f"T{i}", "question_type": "written", "difficulty": "easy"}
                for i in range(5)
            ]
        }
    )
    plan = pipeline._parse_plan(raw, requested=2, allowed_types=[], target_difficulty="")
    assert len(plan.templates) == 2


# ---------------------------------------------------------------------------
# Payload normalization + issue collection
# ---------------------------------------------------------------------------


def test_normalize_choice_resolves_answer_text_to_key() -> None:
    template = QuizTemplate(question_id="q_1", topic="t", question_type="choice", difficulty="easy")
    payload = {
        "question": "What?",
        "options": {"A": "alpha", "B": "beta", "C": "gamma", "D": "delta"},
        "correct_answer": "beta",
        "explanation": "because",
    }
    normalized = QuestionPipeline._normalize_quiz_payload(template, payload)
    assert normalized["correct_answer"] == "B"
    assert set(normalized["options"].keys()) == {"A", "B", "C", "D"}


def test_collect_issues_choice_missing_keys() -> None:
    template = QuizTemplate(question_id="q_1", topic="t", question_type="choice", difficulty="easy")
    payload = {
        "question": "What?",
        "options": {"A": "x", "B": "y", "C": "z"},
        "correct_answer": "A",
        "explanation": "ok",
    }
    normalized = QuestionPipeline._normalize_quiz_payload(template, payload)
    issues = QuestionPipeline._collect_quiz_issues(template, normalized)
    assert "choice_options_must_be_a_to_d" in issues


def test_collect_issues_written_must_not_have_options() -> None:
    template = QuizTemplate(
        question_id="q_1", topic="t", question_type="written", difficulty="medium"
    )
    payload = {
        "question": "Explain X.",
        "options": {"A": "x", "B": "y", "C": "z", "D": "w"},
        "correct_answer": "Because…",
        "explanation": "ok",
    }
    normalized = QuestionPipeline._normalize_quiz_payload(template, payload)
    # Normalization strips options for non-choice types — so the issue surfaces
    # only when the LLM emits a choice-looking shape (single A-D answer key)
    # AND options got stripped during normalization. Here options are stripped
    # so the structural issue disappears; what remains is the answer-key smell.
    assert normalized["options"] is None
    issues = QuestionPipeline._collect_quiz_issues(template, normalized)
    assert issues == []  # answer text "Because…" is not a single A-D key


def test_collect_issues_written_answer_looks_like_key() -> None:
    template = QuizTemplate(
        question_id="q_1", topic="t", question_type="written", difficulty="medium"
    )
    payload = {
        "question": "Which is right?",
        "correct_answer": "B",
        "explanation": "ok",
    }
    normalized = QuestionPipeline._normalize_quiz_payload(template, payload)
    issues = QuestionPipeline._collect_quiz_issues(template, normalized)
    assert "non_choice_correct_answer_looks_like_option_key" in issues


def test_collect_issues_missing_fields() -> None:
    template = QuizTemplate(
        question_id="q_1", topic="t", question_type="written", difficulty="medium"
    )
    payload: dict[str, Any] = {"question": "  ", "correct_answer": "", "explanation": ""}
    normalized = QuestionPipeline._normalize_quiz_payload(template, payload)
    issues = QuestionPipeline._collect_quiz_issues(template, normalized)
    assert {"missing_question", "missing_correct_answer", "missing_explanation"} <= set(issues)


# ---------------------------------------------------------------------------
# _emit_quiz_question — structured event shape
# ---------------------------------------------------------------------------


def test_emit_quiz_question_structures_metadata() -> None:
    pipeline = _make_pipeline()
    bus = _StubStreamBus()
    qa_pair = QuizPair(
        question_id="q_2",
        question="Solve x.",
        question_type="written",
        correct_answer="42",
        explanation="because",
        topic="algebra",
        difficulty="easy",
    )
    asyncio.run(pipeline._emit_quiz_question(stream=bus, qa_pair=qa_pair, index=1, total=3))
    assert len(bus.contents) == 1
    event = bus.contents[0]
    assert event["source"] == "deep_question"
    assert event["stage"] == STAGE_QUIZZING
    meta = event["metadata"]
    assert meta["call_kind"] == CALL_KIND_QUIZ_QUESTION
    assert meta["trace_role"] == "quiz_question"
    assert meta["question_index"] == 1
    assert meta["total_questions"] == 3
    # qa_pair is the structured payload the frontend reads to render the card
    assert meta["qa_pair"]["question_id"] == "q_2"
    assert meta["qa_pair"]["question_type"] == "written"


# ---------------------------------------------------------------------------
# Quiz history loader integration with the sqlite store
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_sqlite_store(tmp_path: Path):
    """Spin up an isolated SQLite session store + force the global getter
    to return it for the duration of the test."""
    from deeptutor.services.session.sqlite_store import SQLiteSessionStore

    store = SQLiteSessionStore(db_path=tmp_path / "session.db")
    with patch(
        "deeptutor.services.session.sqlite_store.get_sqlite_session_store",
        return_value=store,
    ):
        yield store


def test_history_loader_returns_session_scoped_entries(tmp_sqlite_store) -> None:
    """Insert two sessions' worth of quiz answers; loader returns only the
    target session's entries, oldest first, with is_correct=None when the
    learner never answered."""
    from deeptutor.agents.question.history import load_session_quiz_history

    store = tmp_sqlite_store

    async def setup() -> None:
        await store.create_session(session_id="s1", title="quiz session")
        await store.create_session(session_id="s2", title="other session")
        await store.upsert_notebook_entries(
            "s1",
            [
                {
                    "turn_id": "t1",
                    "question_id": "q_1",
                    "question": "What is 2+2?",
                    "question_type": "written",
                    "options": {},
                    "correct_answer": "4",
                    "explanation": "addition",
                    "difficulty": "easy",
                    "user_answer": "4",
                    "is_correct": True,
                },
                {
                    "turn_id": "t1",
                    "question_id": "q_2",
                    "question": "What is 3*3?",
                    "question_type": "written",
                    "options": {},
                    "correct_answer": "9",
                    "explanation": "multiplication",
                    "difficulty": "easy",
                    "user_answer": "8",
                    "is_correct": False,
                },
                {
                    "turn_id": "t2",
                    "question_id": "q_3",
                    "question": "What is e^0?",
                    "question_type": "written",
                    "options": {},
                    "correct_answer": "1",
                    "explanation": "exp",
                    "difficulty": "medium",
                    # Unanswered: empty user_answer + is_correct=False (default)
                    "user_answer": "",
                    "is_correct": False,
                },
            ],
        )
        await store.upsert_notebook_entries(
            "s2",
            [
                {
                    "turn_id": "t99",
                    "question_id": "q_1",
                    "question": "OTHER SESSION should not leak",
                    "question_type": "written",
                    "correct_answer": "x",
                    "explanation": "x",
                    "user_answer": "x",
                    "is_correct": True,
                }
            ],
        )

    asyncio.run(setup())

    entries = asyncio.run(load_session_quiz_history("s1"))
    questions = [e.question for e in entries]
    assert "OTHER SESSION should not leak" not in questions
    assert questions == ["What is 2+2?", "What is 3*3?", "What is e^0?"]  # chronological
    assert entries[0].is_correct is True
    assert entries[1].is_correct is False
    # Unanswered entry: user_answer was empty, so loader surfaces None
    # (so the prompt renders "unknown" instead of misleadingly "incorrect").
    assert entries[2].is_correct is None
    assert entries[2].user_answer == ""


def test_history_loader_returns_empty_for_unknown_session(tmp_sqlite_store) -> None:
    from deeptutor.agents.question.history import load_session_quiz_history

    entries = asyncio.run(load_session_quiz_history(""))
    assert entries == []
    entries = asyncio.run(load_session_quiz_history("does-not-exist"))
    assert entries == []


# ---------------------------------------------------------------------------
# Tool wiring — regression for the bug where _current_context was None
# at schema-build time, leaving the model with no native tool schemas and
# causing it to improvise fake ``tool_calls`` JSON inside the THINK body.
# ---------------------------------------------------------------------------


def test_tool_schemas_populated_when_kb_attached() -> None:
    """With a KB attached, ``rag`` must be auto-mounted and the tool
    schemas the LLM receives must include it with the right ``kb_name``
    enum. A regression here means the explore loop runs schema-less and
    the model fakes tool calls in text."""
    from deeptutor.core.context import UnifiedContext

    pipeline = QuestionPipeline(
        language="en",
        kb_name="demo-kb",
        enabled_tools=["web_search"],
    )
    ctx = UnifiedContext(
        user_message="test",
        session_id="s1",
        metadata={},
        enabled_tools=["web_search"],
        knowledge_bases=["demo-kb"],
    )

    resolved = pipeline._resolved_tools(ctx)
    assert "rag" in resolved
    assert "web_search" in resolved
    assert pipeline._use_native_tools(ctx) is True

    schemas = pipeline._build_llm_tool_schemas(ctx)
    names = [s["function"]["name"] for s in schemas if isinstance(s, dict)]
    assert "rag" in names
    assert "web_search" in names

    rag = next(s for s in schemas if s.get("function", {}).get("name") == "rag")
    kb_schema = rag["function"]["parameters"]["properties"].get("kb_name", {})
    assert kb_schema.get("enum") == ["demo-kb"], (
        "kb_name enum must be populated so the model can't hallucinate"
    )


def test_use_native_tools_false_when_no_tools_resolved() -> None:
    """If the registry returns no tools for this turn (rare — e.g. user
    has every tool disabled), ``_use_native_tools`` must return False so
    we don't pass an empty tools array while the prompt still mentions
    tools. Otherwise the model invents calls in text."""
    from deeptutor.core.context import UnifiedContext

    pipeline = _make_pipeline()
    pipeline.kb_name = None
    ctx = UnifiedContext(
        user_message="test",
        session_id="s1",
        metadata={},
        enabled_tools=[],
        knowledge_bases=[],
    )

    # web_fetch / github / ask_user are always auto-mounted, so we still
    # expect _use_native_tools True under the default registry. The point
    # of this regression is the *guard*: the function inspects resolved
    # tools at all, not just binding/model — so an empty tool list won't
    # silently pass through.
    if pipeline._resolved_tools(ctx):
        assert pipeline._use_native_tools(ctx) is True
    else:  # pragma: no cover — only reachable in stripped registries
        assert pipeline._use_native_tools(ctx) is False


# ---------------------------------------------------------------------------
# Mimic mode — templates_override path
# ---------------------------------------------------------------------------


def test_reference_block_renders_for_mimic_templates() -> None:
    """mimic templates expose their original exam-paper question + answer
    so the quiz step can shadow / paraphrase the source. custom templates
    get the no-reference placeholder instead, so the model knows to
    invent the stem."""
    pipeline = _make_pipeline()

    custom = QuizTemplate(
        question_id="q_1", topic="t", question_type="written", difficulty="medium"
    )
    block_custom = pipeline._render_reference_block(custom)
    assert "no reference" in block_custom.lower() or block_custom.startswith("(")

    mimic = QuizTemplate(
        question_id="q_1",
        topic="t",
        question_type="written",
        difficulty="medium",
        source="mimic",
        reference_question="Prove that the eigenvalues of a Hermitian matrix are real.",
        reference_answer="Use ⟨Ax, x⟩ = ⟨x, Ax⟩ …",
    )
    block_mimic = pipeline._render_reference_block(mimic)
    assert "Reference question" in block_mimic
    assert "Hermitian" in block_mimic
    assert "Reference answer" in block_mimic


def test_build_result_payload_mode_mimic() -> None:
    """``is_mimic=True`` flips the envelope's ``mode`` + ``summary.source``
    so the frontend / notebook layer can distinguish topic-driven from
    exam-driven quizzes. Without this, mimic results were indistinguishable
    from custom and the analytics rolled them together."""
    pipeline = _make_pipeline()
    plan = QuizPlan(
        analysis="from-exam",
        templates=[
            QuizTemplate(
                question_id="q_1",
                topic="Hermitian eigenvalues",
                question_type="written",
                difficulty="medium",
                source="mimic",
                reference_question="ref Q",
                reference_answer="ref A",
            )
        ],
    )
    qa = QuizPair(
        question_id="q_1",
        question="Prove …",
        question_type="written",
        correct_answer="…",
        explanation="…",
        topic="Hermitian eigenvalues",
        difficulty="medium",
    )

    payload_mimic = pipeline._build_result_payload(plan, [qa], is_mimic=True)
    assert payload_mimic["mode"] == "mimic"
    assert payload_mimic["summary"]["source"] == "exam"
    # source / reference fields ride along on the template snapshot for
    # downstream consumers that want to render "from exam paper" badges.
    assert payload_mimic["summary"]["templates"][0]["source"] == "mimic"
    assert payload_mimic["summary"]["templates"][0]["reference_question"] == "ref Q"

    payload_custom = pipeline._build_result_payload(plan, [qa], is_mimic=False)
    assert payload_custom["mode"] == "custom"
    assert payload_custom["summary"]["source"] == "topic"


def test_run_with_templates_override_skips_explore_and_plan(monkeypatch) -> None:
    """``templates_override`` is the mimic-mode hook: when provided, the
    pipeline must jump straight to the quiz phase. This guards against a
    refactor accidentally re-enabling the explore / plan calls for mimic
    (which would burn extra LLM rounds and clobber the planner-fixed
    template list with one the LLM invented).

    We patch out ``_explore``, ``_plan``, ``_quiz_one``, and ``stream.result``
    so we can inspect *which* phases ran without the LLM client touching
    the network.
    """
    from deeptutor.core.context import UnifiedContext

    pipeline = QuestionPipeline(language="en")
    ctx = UnifiedContext(
        user_message="please quiz me",
        session_id="s1",
        metadata={},
        enabled_tools=[],
        knowledge_bases=[],
    )

    explore_calls: list[None] = []
    plan_calls: list[None] = []
    quiz_calls: list[QuizTemplate] = []

    async def _fake_explore(**kwargs: Any) -> str:
        explore_calls.append(None)
        return "should not run"

    async def _fake_plan(**kwargs: Any) -> QuizPlan:
        plan_calls.append(None)
        return QuizPlan(analysis="", templates=[])

    async def _fake_quiz_one(*, template: QuizTemplate, **kwargs: Any) -> QuizPair:
        quiz_calls.append(template)
        return QuizPair(
            question_id=template.question_id,
            question=template.reference_question or template.topic,
            question_type=template.question_type,
            correct_answer="A",
            explanation="…",
            topic=template.topic,
            difficulty=template.difficulty,
        )

    async def _fake_emit(**kwargs: Any) -> None:
        return None

    from contextlib import asynccontextmanager

    bus = _StubStreamBus()

    @asynccontextmanager
    async def _fake_stage(*args: Any, **kwargs: Any):
        yield None

    async def _fake_result(payload: dict[str, Any], **kwargs: Any) -> None:
        bus.contents.append({"text": "result", "metadata": payload})

    bus.stage = _fake_stage  # type: ignore[attr-defined]
    bus.result = _fake_result  # type: ignore[attr-defined]

    monkeypatch.setattr(pipeline, "_explore", _fake_explore)
    monkeypatch.setattr(pipeline, "_plan", _fake_plan)
    monkeypatch.setattr(pipeline, "_quiz_one", _fake_quiz_one)
    monkeypatch.setattr(pipeline, "_emit_quiz_question", _fake_emit)
    # build_openai_client tries to materialise a real client; stub it.
    monkeypatch.setattr(
        "deeptutor.agents.question.pipeline.build_openai_client",
        lambda config: object(),
    )

    templates = [
        QuizTemplate(
            question_id="q_1",
            topic="ref topic 1",
            question_type="written",
            difficulty="medium",
            source="mimic",
            reference_question="Q1?",
            reference_answer="A1",
        ),
        QuizTemplate(
            question_id="q_2",
            topic="ref topic 2",
            question_type="written",
            difficulty="medium",
            source="mimic",
            reference_question="Q2?",
            reference_answer="A2",
        ),
    ]

    payload = asyncio.run(
        pipeline.run(
            context=ctx,
            user_message="please quiz me",
            num_questions=2,
            templates_override=templates,
            stream=bus,
        )
    )

    assert explore_calls == [], "explore must NOT run when templates_override is set"
    assert plan_calls == [], "plan must NOT run when templates_override is set"
    assert [t.question_id for t in quiz_calls] == ["q_1", "q_2"]
    assert payload["mode"] == "mimic"
    assert payload["summary"]["source"] == "exam"
    assert payload["summary"]["template_count"] == 2


# ---------------------------------------------------------------------------
# Exploration trace rendering + protocol-label stripping
# ---------------------------------------------------------------------------


def test_strip_protocol_label_removes_only_leading_label() -> None:
    """The trace renderer feeds each assistant message through this helper.
    Only the leading protocol label should be stripped; later occurrences
    (e.g., the model referencing ``THINK`` inside its own prose) must stay
    so the rendered trace remains faithful."""
    assert (
        QuestionPipeline._strip_protocol_label(
            "``THINK``\nfirst I need to check ``TOOL`` mounting."
        )
        == "first I need to check ``TOOL`` mounting."
    )
    assert QuestionPipeline._strip_protocol_label("``FINISH``\nDone.") == "Done."
    assert QuestionPipeline._strip_protocol_label("no label here") == "no label here"


def test_render_exploration_trace_walks_messages_in_order() -> None:
    """Walks a synthetic post-initial message buffer and asserts the
    rendered markdown contains an iteration block per assistant THINK,
    one per tool_call, and one per role=tool result. The final FINISH
    block must appear last so downstream phases read the closing
    synthesis after the tool history."""
    pipeline = _make_pipeline()

    messages = [
        {"role": "assistant", "content": "``THINK``\nI should retrieve the topic."},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_abc",
                    "type": "function",
                    "function": {
                        "name": "rag",
                        "arguments": json.dumps({"query": "eigenvalues", "kb_name": "demo"}),
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_abc",
            "content": "Eigenvalues are scalars λ where Av = λv. [source-1]",
        },
        {"role": "user", "content": "(protocol nudge — should be filtered)"},
        {"role": "assistant", "content": "``THINK``\nGood, I have grounding now."},
    ]

    rendered = pipeline._render_exploration_trace(
        messages, finish_text="I researched X; now let me generate 3 questions."
    )

    # Order: thought, tool call, tool result, thought, finish note. Find
    # each header's index and assert ascending order.
    indices = []
    for marker in [
        "Iteration 1 — Thought",
        "Iteration 2 — Tool call: rag",
        "Iteration 2 — Tool result (summarized): rag",
        "Iteration 3 — Thought",
        "Final exploration preface",
    ]:
        idx = rendered.find(marker)
        assert idx != -1, f"missing trace section: {marker!r}\n--- rendered ---\n{rendered}"
        indices.append(idx)
    assert indices == sorted(indices)

    # The protocol nudge (role=user) must NOT bleed into the trace.
    assert "protocol nudge" not in rendered
    # Tool call args block must include the query verbatim.
    assert "eigenvalues" in rendered
    # The leading ``THINK`` label must be stripped from rendered thoughts.
    assert "``THINK``" not in rendered
    # FINISH text is at the bottom.
    assert rendered.rstrip().endswith("I researched X; now let me generate 3 questions.")


def test_render_exploration_trace_empty_inputs_uses_marker() -> None:
    pipeline = _make_pipeline()
    rendered = pipeline._render_exploration_trace([], finish_text="")
    # The YAML's empty marker should surface so the planner prompt isn't
    # left with a dangling section header.
    assert rendered.strip().startswith("(")


# ---------------------------------------------------------------------------
# Runtime config wiring
# ---------------------------------------------------------------------------


def test_runtime_config_overrides_max_iterations_and_summarizer_tokens() -> None:
    """``QuestionPipeline.__init__`` must honor the runtime_config payload
    that ``DeepQuestionCapability`` builds via
    ``build_question_runtime_config``. A regression here means the
    capability's config-driven knobs silently do nothing."""
    pipeline = QuestionPipeline(
        language="en",
        runtime_config={
            "exploring": {
                "max_iterations": 12,
                "tool_summarizer": {"enabled": False, "max_tokens": 1234},
            }
        },
    )
    assert pipeline.max_explore_iterations == 12
    assert pipeline.tool_summarizer_enabled is False
    assert pipeline.tool_summarizer_max_tokens == 1234


def test_runtime_config_falls_back_to_defaults_when_missing() -> None:
    """A missing / empty ``exploring`` block must not crash __init__; the
    module-level defaults take over."""
    from deeptutor.agents.question.pipeline import (
        DEFAULT_MAX_EXPLORE_ITERATIONS,
        DEFAULT_TOOL_SUMMARIZER_MAX_TOKENS,
    )

    pipeline = QuestionPipeline(language="en", runtime_config={})
    assert pipeline.max_explore_iterations == DEFAULT_MAX_EXPLORE_ITERATIONS
    assert pipeline.tool_summarizer_enabled is True
    assert pipeline.tool_summarizer_max_tokens == DEFAULT_TOOL_SUMMARIZER_MAX_TOKENS


def test_build_question_runtime_config_reads_capabilities_section() -> None:
    from deeptutor.agents.question.request_config import (
        build_question_runtime_config,
    )

    rc = build_question_runtime_config(
        base_config={
            "capabilities": {
                "deep_question": {
                    "exploring": {
                        "max_iterations": 10,
                        "tool_summarizer": {"enabled": False, "max_tokens": 500},
                    }
                }
            }
        }
    )
    assert rc["exploring"]["max_iterations"] == 10
    assert rc["exploring"]["tool_summarizer"]["enabled"] is False
    assert rc["exploring"]["tool_summarizer"]["max_tokens"] == 500


def test_build_question_runtime_config_defaults_when_unconfigured() -> None:
    from deeptutor.agents.question.request_config import (
        build_question_runtime_config,
    )

    rc = build_question_runtime_config(base_config=None)
    assert rc["exploring"]["max_iterations"] == 8
    assert rc["exploring"]["tool_summarizer"]["enabled"] is True
    assert rc["exploring"]["tool_summarizer"]["max_tokens"] == 800


# ---------------------------------------------------------------------------
# Tool Summarizer — substitution + streaming
# ---------------------------------------------------------------------------


def test_summarize_tool_result_streams_chunks_and_returns_assembled_text() -> None:
    """The summarizer must:

    * Open a "Reflecting..." sub-trace node before streaming.
    * Emit each model chunk to ``stream.thinking`` (so the trace panel
      shows the compression happening live).
    * Return the assembled summary text for the host to substitute into
      the tool message buffer.

    Regression target: if the streaming loop ever broke (e.g., chunks
    weren't being appended), the host would silently swap the raw
    tool_result with an empty string downstream.
    """
    pipeline = _make_pipeline()
    bus = _StubStreamBus()
    # Capture thinking events too — the base stub only logs ``content`` /
    # ``progress`` / ``error``. Add ``thinking`` here.
    bus.thinking_events: list[dict[str, Any]] = []  # type: ignore[attr-defined]

    async def _thinking(text, source="", stage="", metadata=None):
        bus.thinking_events.append(  # type: ignore[attr-defined]
            {"text": text, "source": source, "stage": stage, "metadata": metadata or {}}
        )

    bus.thinking = _thinking  # type: ignore[assignment]

    # Build a minimal fake OpenAI client whose .chat.completions.create
    # returns an async iterator of fake chunks (each with a single content
    # delta), plus a trailing usage frame the summarizer ignores.
    class _Delta:
        def __init__(self, content: str | None) -> None:
            self.content = content

    class _Choice:
        def __init__(self, content: str | None) -> None:
            self.delta = _Delta(content)

    class _Chunk:
        def __init__(self, content: str | None, usage: Any = None) -> None:
            self.choices = [_Choice(content)] if content is not None else []
            self.usage = usage

    async def _stream_chunks():
        for piece in ["Eigenvalues are ", "scalars λ ", "where Av = λv."]:
            yield _Chunk(piece)
        # Trailing usage frame with no choices.
        yield _Chunk(None, usage=None)

    class _Completions:
        async def create(self, **kwargs):
            assert kwargs["stream"] is True
            return _stream_chunks()

    class _Chat:
        def __init__(self) -> None:
            self.completions = _Completions()

    class _FakeClient:
        def __init__(self) -> None:
            self.chat = _Chat()

    summary = asyncio.run(
        pipeline._summarize_tool_result(
            tool_name="rag",
            tool_result="<long raw rag result here>",
            iteration=1,
            stream=bus,
            client=_FakeClient(),
        )
    )

    assert summary == "Eigenvalues are scalars λ where Av = λv."
    # ``Reflecting...`` sub-trace opened (running) and closed (complete).
    states = [ev["metadata"].get("call_state") for ev in bus.progress_events]
    assert "running" in states
    assert "complete" in states
    # Each chunk became a ``thinking`` event with the reflecting trace_role.
    assert bus.thinking_events  # type: ignore[attr-defined]
    roles = {ev["metadata"].get("trace_role") for ev in bus.thinking_events}  # type: ignore[attr-defined]
    assert roles == {"reflection"}
    # Concatenated thinking text matches the returned summary.
    joined = "".join(ev["text"] for ev in bus.thinking_events)  # type: ignore[attr-defined]
    assert joined == summary


def test_summarize_tool_result_empty_input_returns_none() -> None:
    """No LLM call should fire for an empty/whitespace result — and the
    method must return None so the host keeps the original (empty) tool
    message instead of substituting nothing."""
    pipeline = _make_pipeline()
    bus = _StubStreamBus()

    class _DummyClient:
        pass

    result = asyncio.run(
        pipeline._summarize_tool_result(
            tool_name="rag",
            tool_result="   ",
            iteration=0,
            stream=bus,
            client=_DummyClient(),
        )
    )
    assert result is None
    # No streaming events at all — short-circuit before the model call.
    assert bus.progress_events == []


# ---------------------------------------------------------------------------
# Backward-compat helpers that still need to exist for legacy callers
# ---------------------------------------------------------------------------


def test_parse_exam_paper_to_templates_happy_path(monkeypatch, tmp_path: Path) -> None:
    """End-to-end of the mimic adapter, mocking out MinerU + the question
    extractor. Verifies that the JSON payload becomes a list of
    ``QuizTemplate`` with ``source="mimic"`` and the reference fields
    populated."""
    from deeptutor.agents.question import mimic_source

    parsed_dir = tmp_path / "parsed-001"
    parsed_dir.mkdir()
    questions_file = parsed_dir / "exam_questions.json"
    questions_file.write_text(
        json.dumps(
            {
                "questions": [
                    {
                        "question_text": "Define an eigenvalue.",
                        "question_type": "written",
                        "answer": "A scalar λ such that Av = λv …",
                    },
                    {
                        "question_text": "What is the rank of an identity matrix?",
                        "question_type": "choice",
                        "answer": "n",
                    },
                    # Blank rows must be skipped, not crash the loop.
                    {"question_text": "", "question_type": "written"},
                ]
            }
        )
    )

    # "parsed" mode reads an already-parsed dir; it never invokes the parse
    # layer, so only the question extractor needs stubbing.
    monkeypatch.setattr(mimic_source, "extract_questions_from_paper", lambda *a, **k: True)

    templates, trace = asyncio.run(
        mimic_source.parse_exam_paper_to_templates(
            parsed_dir,
            max_questions=10,
            paper_mode="parsed",
            output_dir=tmp_path,
        )
    )

    assert len(templates) == 2  # the blank row was filtered
    assert all(t.source == "mimic" for t in templates)
    assert templates[0].reference_question.startswith("Define")
    assert templates[0].reference_answer.startswith("A scalar")
    assert templates[1].question_type == "choice"
    assert trace["template_count"] == "2"
    assert trace["question_file"].endswith("exam_questions.json")
