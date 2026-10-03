"""SpineSynthesizer behaviour beyond the raw LLM call.

``test_spine_synthesizer_llm_call.py`` covers the ``_call_json`` seam (retry
efforts, stage labels). This file covers everything around it, with the model
replayed from canned strings through ``BaseAgent.stream_llm``:

- payload → chapter/concept-graph materialisation,
- the draft → critique → revise loop and its ``on_round`` events,
- the fallback paths that keep the pipeline alive on unusable model output,
- the deterministic invariants (chapter count, ordering, clamping).

No product code is imported for its side effects and no real LLM is reached.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
import yaml

from deeptutor.agents.base_agent import BaseAgent
from deeptutor.book.agents.spine_synthesizer import (
    SpineSynthesizer,
    _build_chapter_map,
    _clip,
    _ensure_full_coverage,
    _remove_cycles,
    _slug,
)
from deeptutor.book.models import (
    BookProposal,
    Chapter,
    ConceptEdge,
    ConceptGraph,
    ConceptNode,
    ContentType,
    ExplorationReport,
    SourceChunk,
)
from deeptutor.services.config import loader as loader_module
from deeptutor.services.setup.init import DEFAULT_AGENTS_SETTINGS


@pytest.fixture(autouse=True)
def _agent_settings_home(tmp_path, monkeypatch):
    """``get_agent_params`` requires ``data/user/settings/agents.yaml``.

    Tests must not depend on a runtime home seeded by a real install, so every
    test gets its own tmp home holding the shipped defaults.
    """
    settings_dir = tmp_path / "data" / "user" / "settings"
    settings_dir.mkdir(parents=True)
    (settings_dir / "agents.yaml").write_text(
        yaml.safe_dump(DEFAULT_AGENTS_SETTINGS), encoding="utf-8"
    )
    monkeypatch.setattr(loader_module, "PROJECT_ROOT", tmp_path)


def _replay(monkeypatch: pytest.MonkeyPatch, responses: list[str]) -> list[dict[str, Any]]:
    """Replace ``BaseAgent.stream_llm`` with a scripted replay of ``responses``."""
    calls: list[dict[str, Any]] = []
    stream = iter(responses)

    async def _stream_llm(self: BaseAgent, **kwargs: Any):
        calls.append(kwargs)
        yield next(stream, "")

    monkeypatch.setattr(BaseAgent, "stream_llm", _stream_llm)
    return calls


def _proposal() -> BookProposal:
    return BookProposal(
        title="Linear Algebra",
        description="An undergraduate introduction",
        scope="vectors through eigenvalues",
        target_level="undergraduate",
        estimated_chapters=2,
        rationale="core math for CS students",
    )


def _draft_payload() -> dict[str, Any]:
    return {
        "concept_graph": {
            "nodes": [
                {"id": "vectors", "label": "Vectors", "weight": 1.0},
                {"id": "matrices", "label": "Matrices", "weight": 0.8},
            ],
            "edges": [
                {
                    "src": "vectors",
                    "dst": "matrices",
                    "relation": "depends_on",
                    "rationale": "matrices are built on vectors",
                }
            ],
        },
        "chapters": [
            {
                "title": "Vectors",
                "learning_objectives": ["Add vectors", "Scale vectors"],
                "content_type": "theory",
                "summary": "All about vectors.",
                "covers": ["vectors"],
            },
            {
                "title": "Matrices",
                "learning_objectives": ["Multiply matrices"],
                "content_type": "theory",
                "summary": "All about matrices.",
                "covers": ["matrices"],
            },
        ],
    }


def _critique_prompts() -> dict[str, str]:
    return {
        "critique_system": "Critique the draft spine.",
        "critique_user": (
            "Proposal:\n{proposal_block}\n"
            "Exploration:\n{exploration_summary}\n"
            "Draft:\n{draft_block}"
        ),
        "revise_system": "Revise the draft spine.",
        "revise_user": (
            "Proposal:\n{proposal_block}\nCritique:\n{critique_block}\nDraft:\n{draft_block}"
        ),
    }


def _install_prompts(
    monkeypatch: pytest.MonkeyPatch, agent: SpineSynthesizer, mapping: dict[str, str]
) -> None:
    monkeypatch.setattr(agent, "get_prompt", lambda key, *a, **k: mapping.get(key))


# ─────────────────────────────────────────────────────────────────────────────
# ① Normal LLM output parsed into the chapter structure
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_synthesize_parses_valid_payload_into_chapters(monkeypatch) -> None:
    calls = _replay(monkeypatch, [json.dumps(_draft_payload())])
    events: list[str] = []

    def on_round(name: str, payload: dict[str, Any]) -> None:
        events.append(name)

    exploration = ExplorationReport(
        summary="Themes: linear maps and their algebra.",
        candidate_concepts=["vectors", "matrices"],
        chunks=[
            SourceChunk(source="kb", kb_name="math", text="vectors are linear", score=0.9),
        ],
    )
    spine = await SpineSynthesizer(max_rounds=1).synthesize(
        book_id="bk_1",
        proposal=_proposal(),
        exploration=exploration,
        on_round=on_round,
    )

    assert [c.title for c in spine.chapters] == ["Vectors", "Matrices"]
    assert [c.order for c in spine.chapters] == [0, 1]
    assert spine.chapters[0].learning_objectives == ["Add vectors", "Scale vectors"]
    assert spine.chapters[0].content_type is ContentType.THEORY
    assert spine.chapters[0].summary == "All about vectors."
    assert spine.book_id == "bk_1"
    assert spine.exploration_summary == "Themes: linear maps and their algebra."
    # One call only: max_rounds=1 skips critique/revise.
    assert len(calls) == 1
    # The proposal and exploration renders reached the draft prompt.
    assert "title: Linear Algebra" in calls[0]["user_prompt"]
    assert "(no exploration evidence)" not in calls[0]["user_prompt"]
    assert "- [math] vectors are linear" in calls[0]["user_prompt"]
    # A sync on_round callback is accepted and informed of the draft.
    assert events == ["draft"]
    # The user-facing graph is a chapter-level mind map: one node per chapter,
    # the concept dependency lifted to a chapter edge.
    assert {n.id for n in spine.concept_graph.nodes} == {"vectors", "matrices"}
    vectors = spine.chapters[0]
    matrices = spine.chapters[1]
    nodes_by_id = {n.id: n for n in spine.concept_graph.nodes}
    assert nodes_by_id["vectors"].chapter_id == vectors.id
    assert nodes_by_id["matrices"].chapter_id == matrices.id
    assert [(e.src, e.dst, e.relation) for e in spine.concept_graph.edges] == [
        ("vectors", "matrices", "depends_on")
    ]


@pytest.mark.asyncio
async def test_process_adapter_forwards_to_synthesize(monkeypatch) -> None:
    calls = _replay(monkeypatch, [json.dumps(_draft_payload())])

    spine = await SpineSynthesizer(max_rounds=1).process(
        book_id="bk_2",
        proposal=_proposal(),
        exploration=None,
    )

    assert [c.title for c in spine.chapters] == ["Vectors", "Matrices"]
    assert len(calls) == 1


# ─────────────────────────────────────────────────────────────────────────────
# ② Missing fields / illegal JSON / empty output → fallback or explicit stop
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_llm_output_collapses_to_fallback_overview_chapter(monkeypatch) -> None:
    """Both attempts empty (reasoning ate the budget) → single Overview chapter."""
    _replay(monkeypatch, ["", ""])

    spine = await SpineSynthesizer().synthesize(
        book_id="bk_3", proposal=_proposal(), exploration=None
    )

    assert len(spine.chapters) == 1
    fallback = spine.chapters[0]
    assert fallback.title == "Linear Algebra – Overview"
    assert fallback.order == 0
    assert fallback.content_type is ContentType.THEORY
    assert len(fallback.learning_objectives) == 2
    assert fallback.summary == "An undergraduate introduction"


@pytest.mark.asyncio
async def test_illegal_json_output_collapses_to_fallback_overview_chapter(monkeypatch) -> None:
    _replay(monkeypatch, ["this is {{ definitely not json", "still { not json"])

    spine = await SpineSynthesizer().synthesize(
        book_id="bk_4", proposal=_proposal(), exploration=None
    )

    assert [c.title for c in spine.chapters] == ["Linear Algebra – Overview"]
    assert spine.chapters[0].order == 0


@pytest.mark.asyncio
async def test_payload_without_chapters_key_still_yields_fallback_spine(monkeypatch) -> None:
    """A payload that keeps the graph but lost ``chapters`` must not crash."""
    _replay(
        monkeypatch,
        [
            json.dumps(
                {"concept_graph": {"nodes": [{"id": "vectors", "label": "Vectors"}], "edges": []}}
            ),
            "",
        ],
    )

    spine = await SpineSynthesizer().synthesize(
        book_id="bk_5", proposal=_proposal(), exploration=None
    )

    assert [c.title for c in spine.chapters] == ["Linear Algebra – Overview"]
    # The surviving concept is re-attached to the fallback chapter.
    assert spine.concept_graph.nodes[0].chapter_id == spine.chapters[0].id


@pytest.mark.asyncio
async def test_critique_with_issues_triggers_revision(monkeypatch) -> None:
    draft = _draft_payload()
    critique = {"issues": ["vectors must precede matrices"], "verdict": "revise"}
    revised = json.loads(json.dumps(draft))
    revised["chapters"][0]["summary"] = "Revised vectors chapter."
    calls = _replay(
        monkeypatch,
        [json.dumps(draft), json.dumps(critique), json.dumps(revised)],
    )
    events: list[str] = []

    async def on_round(name: str, payload: dict[str, Any]) -> None:
        events.append(name)

    agent = SpineSynthesizer()
    _install_prompts(monkeypatch, agent, _critique_prompts())

    spine = await agent.synthesize(
        book_id="bk_6", proposal=_proposal(), exploration=None, on_round=on_round
    )

    assert events == ["draft", "critique_1", "revise_1"]
    assert [c["stage"] for c in calls] == ["spine_draft", "spine_critique", "spine_revise"]
    # The critique prompt carried the serialized draft.
    assert "Vectors" in calls[1]["user_prompt"]
    assert spine.chapters[0].summary == "Revised vectors chapter."
    assert [c.order for c in spine.chapters] == [0, 1]


@pytest.mark.asyncio
async def test_ok_verdict_skips_revision(monkeypatch) -> None:
    draft = _draft_payload()
    calls = _replay(
        monkeypatch,
        [json.dumps(draft), json.dumps({"issues": [], "verdict": "ok"})],
    )
    events: list[str] = []

    async def on_round(name: str, payload: dict[str, Any]) -> None:
        events.append(name)

    agent = SpineSynthesizer()
    _install_prompts(monkeypatch, agent, _critique_prompts())

    spine = await agent.synthesize(
        book_id="bk_7", proposal=_proposal(), exploration=None, on_round=on_round
    )

    assert events == ["draft", "critique_1"]
    assert len(calls) == 2
    # The un-revised draft is what materialised.
    assert spine.chapters[0].summary == "All about vectors."


@pytest.mark.asyncio
async def test_unparseable_critique_is_treated_as_no_issues(monkeypatch) -> None:
    draft = _draft_payload()
    calls = _replay(monkeypatch, [json.dumps(draft), "garbage", "garbage"])
    events: list[str] = []

    async def on_round(name: str, payload: dict[str, Any]) -> None:
        events.append(name)

    agent = SpineSynthesizer()
    _install_prompts(monkeypatch, agent, _critique_prompts())

    spine = await agent.synthesize(
        book_id="bk_8", proposal=_proposal(), exploration=None, on_round=on_round
    )

    # The critique stage retried once and still produced nothing dict-shaped,
    # so the loop stops instead of revising against an imagined critique.
    assert events == ["draft", "critique_1"]
    assert len(calls) == 3
    assert spine.chapters[0].summary == "All about vectors."


@pytest.mark.asyncio
async def test_missing_revise_prompts_keep_the_draft(monkeypatch) -> None:
    draft = _draft_payload()
    critique = {"issues": ["needs work"], "verdict": "revise"}
    calls = _replay(monkeypatch, [json.dumps(draft), json.dumps(critique), "{}"])
    events: list[str] = []

    async def on_round(name: str, payload: dict[str, Any]) -> None:
        events.append(name)

    agent = SpineSynthesizer()
    _install_prompts(
        monkeypatch,
        agent,
        {
            "critique_system": "Critique the draft spine.",
            "critique_user": "Draft:\n{draft_block}",
        },
    )

    spine = await agent.synthesize(
        book_id="bk_9", proposal=_proposal(), exploration=None, on_round=on_round
    )

    assert events == ["draft", "critique_1"]
    assert len(calls) == 2  # revise prompt absent → never called
    assert spine.chapters[0].summary == "All about vectors."


# ─────────────────────────────────────────────────────────────────────────────
# ③ Invariants: count, order, clamping
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_chapters_are_reordered_to_follow_concept_dependencies(monkeypatch) -> None:
    """The LLM listed Matrices first, but Matrices depends on Vectors."""
    payload = _draft_payload()
    payload["chapters"] = list(reversed(payload["chapters"]))
    _replay(monkeypatch, [json.dumps(payload)])

    spine = await SpineSynthesizer(max_rounds=1).synthesize(
        book_id="bk_10", proposal=_proposal(), exploration=None
    )

    assert [c.title for c in spine.chapters] == ["Vectors", "Matrices"]
    assert [c.order for c in spine.chapters] == [0, 1]


@pytest.mark.asyncio
async def test_cyclic_concepts_preserve_the_chapter_count(monkeypatch) -> None:
    payload = {
        "concept_graph": {
            "nodes": [
                {"id": "a", "label": "A"},
                {"id": "b", "label": "B"},
            ],
            "edges": [
                {"src": "a", "dst": "b", "relation": "depends_on", "rationale": "b builds on a"},
                {"src": "b", "dst": "a", "relation": "depends_on", "rationale": ""},
            ],
        },
        "chapters": [
            {"title": "Alpha", "covers": ["a"]},
            {"title": "Beta", "covers": ["b"]},
        ],
    }
    _replay(monkeypatch, [json.dumps(payload)])

    spine = await SpineSynthesizer(max_rounds=1).synthesize(
        book_id="bk_11", proposal=_proposal(), exploration=None
    )

    assert len(spine.chapters) == 2
    assert [c.title for c in spine.chapters] == ["Alpha", "Beta"]
    assert [c.order for c in spine.chapters] == [0, 1]


def test_coerce_chapters_skips_unusable_entries() -> None:
    raw: list[Any] = [
        "just a string",
        {"title": ""},
        {"summary": "no title at all"},
        {"title": "Vectors"},
        {"title": "vectors"},  # duplicate, case-insensitive
        42,
        {"title": "Matrices"},
    ]

    chapters = SpineSynthesizer._coerce_chapters(raw, ConceptGraph())

    assert [c.title for c in chapters] == ["Vectors", "Matrices"]


def test_coerce_chapters_clamps_and_normalizes_llm_noise() -> None:
    graph = ConceptGraph(nodes=[ConceptNode(id="vectors", label="Vectors")])
    raw = [
        {
            "title": "T" * 200,
            "learning_objectives": [f"objective {i}" for i in range(10)] + ["", "   "],
            "content_type": "overview",  # reserved for the engine chapter
            "prerequisites": [f"prereq {i}" for i in range(6)] + ["", None],
            "source_anchors": [
                {"kind": "kb", "kb_name": "math", "ref": "d1", "snippet": "s"} for _ in range(8)
            ],
            "covers": ["vectors", "unknown_concept", "", "vectors"],
            "summary": "S" * 500,
        },
        {
            "title": "Quantum",
            "content_type": "quantum",  # not a ContentType value
        },
    ]

    first, second = SpineSynthesizer._coerce_chapters(raw, graph)

    assert first.title == "T" * 160 + "…"
    assert len(first.learning_objectives) == 6
    assert len(first.prerequisites) == 4
    assert len(first.source_anchors) == 6
    assert first.source_anchors[0].kb_name == "math"
    assert first.summary == "S" * 400 + "…"
    assert first.content_type is ContentType.THEORY
    assert (first.__pydantic_extra__ or {}).get("covers") == ["vectors"]
    assert second.content_type is ContentType.THEORY


def test_coerce_graph_drops_unusable_nodes_and_edges() -> None:
    raw: Any = {
        "nodes": [
            {"id": "Vectors!", "label": "Vectors", "weight": 5},  # slug + clamp to 1.0
            {"id": "matrices", "label": "Matrices", "weight": "oops"},  # bad weight → 1.0
            {"label": ""},  # no label → dropped
            "not-a-dict",  # skipped
            {"id": "vectors", "label": "Vectors again"},  # duplicate id → dropped
        ],
        "edges": [
            {"src": "vectors", "dst": "matrices", "relation": "EXTENDS", "rationale": "r"},
            {"src": "vectors", "dst": "vectors"},  # self edge → dropped
            {"src": "vectors", "dst": "ghost"},  # unknown node → dropped
            {
                "src": "vectors",
                "dst": "matrices",
                "relation": "extends",
                "rationale": "r",
            },  # duplicate → dropped
            {"src": "vectors", "dst": "matrices", "relation": "weird"},  # → depends_on
        ],
    }

    graph = SpineSynthesizer._coerce_graph(raw)

    assert [n.id for n in graph.nodes] == ["vectors", "matrices"]
    assert graph.nodes[0].weight == 1.0
    assert graph.nodes[1].weight == 1.0
    assert [(e.src, e.dst, e.relation) for e in graph.edges] == [
        ("vectors", "matrices", "extends"),
        ("vectors", "matrices", "depends_on"),
    ]
    empty = SpineSynthesizer._coerce_graph(None)
    assert empty.nodes == []
    assert empty.edges == []
    also_empty = SpineSynthesizer._coerce_graph(["chapters", "not", "a", "graph"])
    assert also_empty.nodes == []


def test_remove_cycles_drops_the_least_justified_edge() -> None:
    graph = ConceptGraph(
        nodes=[ConceptNode(id=n, label=n.upper()) for n in ("a", "b", "c")],
        edges=[
            ConceptEdge(src="a", dst="b", relation="depends_on", rationale="x"),
            ConceptEdge(src="b", dst="c", relation="depends_on", rationale="long justification"),
            ConceptEdge(src="c", dst="a", relation="depends_on", rationale="yy"),
        ],
    )

    result = _remove_cycles(graph)

    assert [(e.src, e.dst) for e in result.edges] == [("b", "c"), ("c", "a")]
    # The nodes are untouched.
    assert [n.id for n in result.nodes] == ["a", "b", "c"]


def test_uncovered_concept_joins_the_most_relevant_chapter() -> None:
    raw = [
        {
            "title": "Vector operations",
            "summary": "dot products and cross products of vectors",
            "covers": ["vectors"],
        },
        {"title": "A short history", "summary": "how algebra evolved over centuries"},
    ]
    graph = ConceptGraph(
        nodes=[
            ConceptNode(id="vectors", label="Vectors"),
            ConceptNode(
                id="euclidean_spaces",
                label="Euclidean spaces",
                description="the geometry of vector spaces",
            ),
        ]
    )
    chapters = SpineSynthesizer._coerce_chapters(raw, graph)

    result = _ensure_full_coverage(chapters, graph)

    vec_ch, hist_ch = chapters
    assert "euclidean_spaces" in (vec_ch.__pydantic_extra__ or {}).get("covers", [])
    assert "euclidean_spaces" not in (hist_ch.__pydantic_extra__ or {}).get("covers", [])
    by_id = {n.id: n for n in result.nodes}
    assert by_id["euclidean_spaces"].chapter_id == vec_ch.id
    assert by_id["vectors"].chapter_id == vec_ch.id


def test_chapter_map_adds_virtual_root_for_disconnected_chapters() -> None:
    chapters = [Chapter(title="Vectors"), Chapter(title="Matrices")]

    cmap = _build_chapter_map(chapters, ConceptGraph(), book_title="Linear Algebra")

    assert cmap.nodes[0].id == "linear_algebra"
    assert cmap.nodes[0].label == "Linear Algebra"
    assert {n.id for n in cmap.nodes} == {"linear_algebra", "vectors", "matrices"}
    assert {(e.src, e.dst, e.relation) for e in cmap.edges} == {
        ("linear_algebra", "vectors", "related"),
        ("linear_algebra", "matrices", "related"),
    }


def test_chapter_map_matches_prerequisite_titles_to_chapter_edges() -> None:
    chapters = [
        Chapter(title="Vectors"),
        Chapter(title="Matrices", prerequisites=["Vectors"]),
    ]

    cmap = _build_chapter_map(chapters, ConceptGraph(), book_title="Linear Algebra")

    # Both chapters are roots of the concept graph (no edges), so the virtual
    # root appears; the explicit prerequisite still produces its own edge.
    assert ("vectors", "matrices", "depends_on") in {(e.src, e.dst, e.relation) for e in cmap.edges}


def test_render_proposal_and_chunks_shape_the_prompts() -> None:
    text = SpineSynthesizer._render_proposal(_proposal())
    assert "title: Linear Algebra" in text
    assert "estimated_chapters: 2" in text
    assert "rationale: core math for CS students" in text

    assert SpineSynthesizer._render_chunks(None) == "(no exploration evidence)"
    assert SpineSynthesizer._render_chunks(ExplorationReport()) == "(no exploration evidence)"

    report = ExplorationReport(
        chunks=[
            SourceChunk(source="kb", kb_name="math", text="vectors text", score=0.2),
            SourceChunk(source="chat", kb_name="", text="chat text", score=0.9),
            SourceChunk(source="kb", kb_name="math", text="mid text", score=0.5),
        ]
    )
    block = SpineSynthesizer._render_chunks(report)
    assert block.splitlines() == [
        "- [chat] chat text",
        "- [math] mid text",
        "- [math] vectors text",
    ]


def test_clip_and_slug_helpers_are_tolerant_of_garbage() -> None:
    assert _clip(None, 10) == ""
    assert _clip("  hi  ", 10) == "hi"
    assert _clip("ab", 5) == "ab"
    assert _clip("abcdefghij", 5) == "abcde…"

    assert _slug("!!") == "concept"
    assert _slug(None) == "concept"
    assert _slug("Hello, World!") == "hello_world"
    assert _slug("  A  B  ") == "a_b"
    assert len(_slug("x" * 100)) == 48
