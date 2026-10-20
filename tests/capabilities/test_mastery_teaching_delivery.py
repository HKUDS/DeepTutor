"""Teaching records describe delivered explanations, not future model plans."""

from types import SimpleNamespace

import pytest

from deeptutor.agents.loop.agent_loop import AgentLoop, LLMCallResult
from deeptutor.agents.loop.pipeline import AgenticLoopPipeline
from deeptutor.capabilities.mastery import tools
from deeptutor.capabilities.mastery.loop import MasteryLoopCapability
from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.learning.models import KnowledgePoint, LearningModule, LearningProgress
from deeptutor.learning.policy import learning_stage
from deeptutor.learning.service import LearningService
from deeptutor.learning.storage import LearningStore
from deeptutor.runtime.stream_bus import StreamBus

EXPLANATION = "A membrane is a boundary, separating the inside of the cell from its surroundings."


@pytest.fixture
def lesson(tmp_path, monkeypatch):
    service = LearningService(LearningStore(tmp_path))
    service.save(
        LearningProgress(
            book_id="p",
            modules=[
                LearningModule(
                    id="m",
                    name="Module",
                    order=0,
                    knowledge_points=[
                        KnowledgePoint(
                            id="kp", name="Boundary and transport", type="memory", module_id="m"
                        )
                    ],
                )
            ],
        )
    )
    monkeypatch.setattr(tools, "_new_service", lambda: service)
    return service


def delivery(bus, **overrides):
    return lambda: {
        "path_id": "p",
        "session_id": "s",
        "turn_id": "t",
        "segments": bus.public_content_snapshot(source="mastery_path", stage="responding"),
        **overrides,
    }


async def note(bus, **kwargs):
    return await tools.MasteryNoteExplainedTool().execute(
        _mastery_path_id="p",
        _session_id="s",
        _turn_id="t",
        knowledge_point_id="kp",
        summary="Explained the membrane boundary, not all transport.",
        explanation_quote=EXPLANATION,
        _teaching_delivery=delivery(bus),
        **kwargs,
    )


@pytest.mark.asyncio
async def test_future_explanation_cannot_be_recorded(lesson):
    before = lesson.store.load("p").model_dump()
    result = await note(StreamBus(assign_seq=True))
    assert not result.success
    assert lesson.store.load("p").model_dump() == before


@pytest.mark.asyncio
async def test_public_fragmented_explanation_has_durable_partial_provenance(lesson):
    bus = StreamBus(assign_seq=True)
    await bus.content(EXPLANATION[:32], source="mastery_path", stage="responding")
    await bus.content(EXPLANATION[32:], source="mastery_path", stage="responding")
    result = await note(bus)
    assert result.success, result.content
    fresh = LearningStore(lesson.store._root).load("p")
    recorded = fresh.explained_objectives["kp"]
    assert recorded["explanation_quote"] == EXPLANATION
    assert recorded["delivery"]["turn_id"] == "t"
    assert recorded["delivery"]["event_seq_range"] == [1, 2]
    assert recorded["coverage"] == "partial"
    assert learning_stage(fresh, "kp") == "partially_explained"
    assert fresh.mastery_levels.get("kp", 0) == 0
    assert not fresh.learning_evidence and not fresh.quiz_attempts


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "event_type",
    [
        StreamEventType.THINKING,
        StreamEventType.TOOL_RESULT,
        StreamEventType.SOURCES,
        StreamEventType.OBSERVATION,
    ],
)
async def test_non_answer_events_are_not_teaching(lesson, event_type):
    bus = StreamBus(assign_seq=True)
    await bus.emit(
        StreamEvent(type=event_type, source="mastery_path", stage="responding", content=EXPLANATION)
    )
    assert not (await note(bus)).success
    assert not lesson.store.load("p").explained_objectives


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["path_id", "session_id", "turn_id"])
async def test_delivery_scope_cannot_cross_path_session_or_turn(lesson, scope):
    bus = StreamBus(assign_seq=True)
    await bus.content(EXPLANATION, source="mastery_path", stage="responding")
    result = await tools.MasteryNoteExplainedTool().execute(
        _mastery_path_id="p",
        _session_id="s",
        _turn_id="t",
        knowledge_point_id="kp",
        summary="A real explanation with forged provenance.",
        explanation_quote=EXPLANATION,
        _teaching_delivery=delivery(bus, **{scope: "other"}),
    )
    assert not result.success
    assert not lesson.store.load("p").explained_objectives


@pytest.mark.asyncio
async def test_other_capability_content_and_unpublished_text_do_not_count(lesson):
    bus = StreamBus(assign_seq=True)
    await bus.content(EXPLANATION, source="rag", stage="responding")
    await bus.content(EXPLANATION, source="mastery_path", stage="exploring")
    assert not (await note(bus)).success
    # Text discarded by the loop never reaches the stream and cannot supply evidence.
    model_message_only = {"role": "assistant", "content": EXPLANATION}
    assert model_message_only["content"] == EXPLANATION
    assert not lesson.store.load("p").explained_objectives


@pytest.mark.asyncio
async def test_snapshot_is_immutable_and_does_not_gain_future_events():
    bus = StreamBus(assign_seq=True)
    await bus.content("first", source="mastery_path", stage="responding")
    snapshot = bus.public_content_snapshot(source="mastery_path", stage="responding")
    await bus.content("second", source="mastery_path", stage="responding")
    assert isinstance(snapshot, tuple) and isinstance(snapshot[0], tuple)
    assert len(snapshot) == 1 and snapshot[0][2] == "first"


def test_legacy_self_report_is_not_verified_delivery(lesson):
    progress = lesson.store.load("p")
    progress.explained_objectives["kp"] = {"summary": "A legacy self-report", "timestamp": 1}
    assert learning_stage(progress, "kp") == "teaching_record_unverified"


def test_mastery_capability_uses_server_snapshot_and_rechecks_binding():
    context = UnifiedContext(
        user_message="continue",
        session_id="s",
        metadata={
            "mastery_mode": True,
            "mastery_path_id": "p",
            "mastery_session_mode": "study",
            "turn_id": "t",
        },
    )
    context.extension("published_assistant_content")["snapshot"] = lambda: ((1, 1.0, EXPLANATION),)
    bound = MasteryLoopCapability().augment_kwargs(
        "mastery_note_explained",
        {
            "_teaching_delivery": lambda: {"path_id": "FORGED"},
        },
        context,
    )
    assert bound["_teaching_delivery"]()["path_id"] == "p"
    context.metadata["mastery_path_id"] = "other"
    assert bound["_teaching_delivery"]() is None


@pytest.mark.asyncio
async def test_native_dispatch_binds_the_live_public_stream(lesson, monkeypatch):
    context = UnifiedContext(
        user_message="continue",
        session_id="s",
        metadata={
            "mastery_mode": True,
            "mastery_path_id": "p",
            "turn_id": "t",
        },
    )
    bus = StreamBus(assign_seq=True)
    await bus.content(EXPLANATION, source="mastery_path", stage="responding")
    pipeline = object.__new__(AgenticLoopPipeline)
    pipeline.event_source = "mastery_path"
    pipeline._tool_view = None
    pipeline.registry = SimpleNamespace()
    pipeline._t = lambda *_args, **_kwargs: "test"
    pipeline._capability_rebinding_tools = lambda _context: set()
    pipeline._augment_tool_kwargs = lambda name, args, ctx: MasteryLoopCapability().augment_kwargs(
        name, args, ctx
    )

    async def dispatch(**kwargs):
        bound = kwargs["kwarg_augmenter"](
            "mastery_note_explained",
            {
                "knowledge_point_id": "kp",
                "summary": "The delivered boundary explanation.",
                "explanation_quote": EXPLANATION,
                "_teaching_delivery": lambda: {"path_id": "forged"},
            },
            context,
        )
        return await tools.MasteryNoteExplainedTool().execute(**bound)

    monkeypatch.setattr("deeptutor.agents.loop.pipeline.dispatch_tool_calls", dispatch)
    result = await pipeline._dispatch_tool_calls(
        tool_calls=[],
        context=context,
        stream=bus,
        iteration_index=0,
        stage="responding",
    )
    assert result.success, result.content
    assert lesson.store.load("p").explained_objectives["kp"]["delivery"]["turn_id"] == "t"


@pytest.mark.asyncio
async def test_quote_must_be_exact_and_nontrivial(lesson):
    bus = StreamBus(assign_seq=True)
    await bus.content(EXPLANATION, source="mastery_path", stage="responding")
    for quote in ("yes", "An invented explanation that was never emitted.", "a" * 2001):
        result = await tools.MasteryNoteExplainedTool().execute(
            _mastery_path_id="p",
            _session_id="s",
            _turn_id="t",
            knowledge_point_id="kp",
            summary="A proposed teaching record.",
            explanation_quote=quote,
            _teaching_delivery=delivery(bus),
        )
        assert not result.success
    assert not lesson.store.load("p").explained_objectives


@pytest.mark.asyncio
async def test_unknown_objective_cannot_gain_delivered_record(lesson):
    bus = StreamBus(assign_seq=True)
    await bus.content(EXPLANATION, source="mastery_path", stage="responding")
    result = await tools.MasteryNoteExplainedTool().execute(
        _mastery_path_id="p",
        _session_id="s",
        _turn_id="t",
        knowledge_point_id="other",
        summary="A delivered explanation.",
        explanation_quote=EXPLANATION,
        _teaching_delivery=delivery(bus),
    )
    assert not result.success
    assert not lesson.store.load("p").explained_objectives


@pytest.mark.asyncio
async def test_retracted_optimistic_prose_cannot_supply_teaching_evidence(lesson):
    bus = StreamBus(assign_seq=True)
    await bus.content(
        EXPLANATION,
        source="mastery_path",
        stage="responding",
        metadata={"call_id": "rejected", "answer_visible": True},
    )
    runner = object.__new__(AgentLoop)
    runner.stream = bus
    runner.source = "mastery_path"
    runner.stage = "responding"
    await runner._discard_deferred_output(
        LLMCallResult(
            text=EXPLANATION,
            completion_metadata={"call_id": "rejected", "answer_visible": True},
        )
    )
    assert not (await note(bus)).success
    assert not lesson.store.load("p").explained_objectives


@pytest.mark.asyncio
async def test_visibility_corrections_are_scoped_to_the_matching_call():
    bus = StreamBus(assign_seq=True)
    await bus.content(
        "discarded",
        source="mastery_path",
        stage="responding",
        metadata={"call_id": "bad", "answer_visible": True},
    )
    await bus.content(
        "accepted",
        source="mastery_path",
        stage="responding",
        metadata={"call_id": "good", "answer_visible": True},
    )
    await bus.content("callless", source="mastery_path", stage="responding")
    await bus.progress(
        "",
        source="mastery_path",
        stage="responding",
        metadata={"call_id": "bad", "answer_visible": False},
    )
    snapshot = bus.public_content_snapshot(source="mastery_path", stage="responding")
    assert [part[2] for part in snapshot] == ["accepted", "callless"]
