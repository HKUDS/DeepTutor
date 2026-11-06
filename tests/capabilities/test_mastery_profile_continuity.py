"""Profile updates preserve standing context across sessions and tool retries."""

import json

import pytest

from deeptutor.capabilities.mastery.tools import MasteryProfileTool, MasteryStatusTool
from deeptutor.learning.models import KnowledgePoint, LearningModule
from deeptutor.learning.service import LearningService
from deeptutor.learning.storage import LearningConflictError, LearningStore


@pytest.fixture
def system(tmp_path, monkeypatch):
    store = LearningStore(root=tmp_path)
    service = LearningService(store)
    service.replace_modules_for_path(
        "path",
        [
            LearningModule(
                id="m",
                name="Basics",
                order=0,
                knowledge_points=[
                    KnowledgePoint(id="p", name="Boundary", module_id="m", type="concept")
                ],
            )
        ],
    )
    monkeypatch.setattr("deeptutor.capabilities.mastery.tools._new_service", lambda: service)
    service.record_learner_profile(
        "path",
        fields={
            "prior_knowledge": "Basic algebra",
            "target_level": "Explain independently",
            "time_budget": "Two weeks",
            "preferences": "Use diagrams",
            "notes": "Evening study",
        },
        session_id="first",
    )
    return store, service


@pytest.mark.asyncio
@pytest.mark.parametrize("updates", [None, []])
async def test_empty_teaching_updates_allow_intake_but_not_empty_writes(system, updates):
    store, _ = system
    tool = MasteryProfileTool()
    result = await tool.execute(
        _mastery_path_id="path", preferences="Project driven", teaching_updates=updates
    )
    assert result.success, result.content
    assert store.load("path").learner_profile.preferences == "Project driven"
    empty = await tool.execute(_mastery_path_id="path", teaching_updates=updates)
    assert not empty.success


@pytest.mark.asyncio
async def test_profile_accepts_actual_turn_answers_and_rejects_other_sources(system):
    from deeptutor.capabilities.mastery.loop import MasteryLoopCapability
    from deeptutor.core.context import UnifiedContext

    store, _ = system
    context = UnifiedContext(
        user_message="Design an outline",
        metadata={"mastery_mode": True, "mastery_path_id": "path", "turn_id": "turn"},
    )
    context.record_user_input("Project driven", source="ask_user", input_id="call:q1")
    cap = MasteryLoopCapability()
    update = {
        "kind": "preference",
        "op": "upsert",
        "key": "style",
        "text": "Projects",
        "basis": "learner_report",
        "evidence": "Project driven",
    }
    arguments = {"teaching_updates": [update], "expected_revision": store.load("path").version}
    result = await MasteryProfileTool().execute(
        **cap.augment_kwargs("mastery_profile", arguments, context)
    )
    assert result.success, result.content
    update["evidence"] = "Invented by the model"
    arguments["expected_revision"] = store.load("path").version
    result = await MasteryProfileTool().execute(
        **cap.augment_kwargs("mastery_profile", arguments, context)
    )
    assert not result.success


def test_finish_decision_is_pure_and_distinguishes_optional_repair():
    from deeptutor.capabilities.mastery.loop import MasteryLoopCapability
    from deeptutor.core.context import UnifiedContext

    context = UnifiedContext(metadata={"mastery_mode": True})
    state = context.extension("mastery")
    state["profile_write_pending"] = True
    cap = MasteryLoopCapability()
    decision = cap.finish_decision(context, "")
    assert decision.instruction and not decision.blocking
    assert cap.finish_decision(context, "") == decision
    assert "profile_repair_requested" not in state
    cap.on_finish_redirect(context)
    assert not cap.finish_decision(context, "").instruction
    state["quiz_requested"] = True
    assert cap.finish_decision(context, "").blocking
    state.pop("profile_repair_requested")
    cap.on_finish_redirect(context)
    assert "profile_repair_requested" not in state
    state.update(outline_write_pending=True, card_posted=True)
    assert cap.final_text_override(context, "") is None
    assert cap.finish_decision(context, "").blocking


@pytest.mark.asyncio
async def test_blank_optional_arguments_do_not_erase_intake_during_feedback(system, tmp_path):
    store, service = system
    before = store.load("path")
    result = await MasteryProfileTool().execute(
        _mastery_path_id="path",
        _session_id="second",
        prior_knowledge="",
        target_level=None,
        time_budget="  ",
        preferences="",
        notes="",
        expected_revision=before.version,
        _learner_message="Use connected explanations.",
        teaching_updates=[
            {
                "kind": "preference",
                "op": "upsert",
                "key": "pace",
                "text": "Use connected explanations",
                "basis": "learner_report",
                "evidence": "Use connected explanations.",
            }
        ],
    )
    assert result.success, result.content
    loaded = LearningStore(root=tmp_path).load("path")
    for name in ("prior_knowledge", "target_level", "time_budget", "preferences", "notes"):
        assert getattr(loaded.learner_profile, name) == getattr(before.learner_profile, name)
    assert json.loads(result.content)["updated_fields"] == ["teaching_preferences"]
    # Direct service callers receive the same partial-update semantics.
    after, changed = service.record_learner_profile(
        "path", fields={"notes": "  ", "time_budget": None}
    )
    assert changed == [] and after.version == loaded.version


@pytest.mark.asyncio
async def test_current_correction_survives_new_session_and_keeps_unrelated_preferences(system):
    store, service = system
    service.record_learner_profile(
        "path",
        fields={"preferences": "Connected explanations now"},
        session_id="later",
        turn_id="correction",
    )
    status = json.loads(
        (
            await MasteryStatusTool().execute(_mastery_path_id="path", _session_id="fresh-session")
        ).content
    )
    assert status["learner_profile"]["preferences"] == "Connected explanations now"
    assert status["learner_profile"]["time_budget"] == "Two weeks"
    assert (
        "fresh path preferences over conflicting historical summaries"
        in status["learner_profile"]["teaching_guidance"]
    )


def test_clear_is_explicit_quoted_revision_fenced_and_idempotent(system):
    store, service = system
    revision = store.load("path").version
    request = "Forget my old time budget."
    kwargs = dict(
        fields={},
        clear_fields=["time_budget"],
        clear_request=request,
        learner_message=request,
        expected_revision=revision,
    )
    progress, changed = service.record_learner_profile("path", **kwargs)
    assert changed == ["time_budget"]
    assert progress.learner_profile.time_budget == ""
    assert progress.learner_profile.preferences == "Use diagrams"
    again, changed = service.record_learner_profile("path", **kwargs)
    assert changed == [] and again.version == progress.version
    with pytest.raises(ValueError, match="literal quote"):
        service.record_learner_profile("path", **{**kwargs, "learner_message": "Teach me next"})
    with pytest.raises(LearningConflictError):
        service.record_learner_profile("path", **{**kwargs, "clear_fields": ["notes"]})


@pytest.mark.asyncio
async def test_selected_profile_write_needs_a_successful_native_receipt(system):
    from deeptutor.capabilities.mastery.loop import MasteryLoopCapability
    from deeptutor.core.context import UnifiedContext

    cap = MasteryLoopCapability()
    context = UnifiedContext(
        user_message="Use connected explanations.",
        session_id="new",
        metadata={"mastery_mode": True, "mastery_path_id": "path"},
    )
    kwargs = cap.augment_kwargs("mastery_profile", {"teaching_strategy": "invalid"}, context)
    failure = await MasteryProfileTool().execute(**kwargs)
    assert not failure.success
    assert "mastery_profile" in cap.finish_instruction(context, "Saved for next time.")
    corrected = cap.augment_kwargs(
        "mastery_profile", {"preferences": "Connected explanations"}, context
    )
    result = await MasteryProfileTool().execute(**corrected)
    assert result.success
    assert cap.finish_instruction(context, "Saved for next time.") is None
    assert context.extension("mastery")["profile_receipt"]["updated_fields"] == ["preferences"]


@pytest.mark.asyncio
async def test_profile_failure_has_one_repair_round_then_teaching_with_unsaved_notice(system):
    from deeptutor.capabilities.mastery.loop import MasteryLoopCapability
    from deeptutor.core.context import UnifiedContext

    cap = MasteryLoopCapability()
    context = UnifiedContext(
        user_message="Use connected explanations.",
        metadata={"mastery_mode": True, "mastery_path_id": "path"},
    )
    result = await MasteryProfileTool().execute(
        **cap.augment_kwargs("mastery_profile", {"teaching_strategy": "invalid"}, context)
    )
    assert not result.success
    assert cap.finish_instruction(context, "Saved for next time.") is not None
    cap.on_finish_redirect(context)
    teaching = (
        "A boundary separates the two regions. We can follow their relationship step by step."
    )
    assert cap.finish_instruction(context, teaching) is None
    visible = cap.final_text_override(context, teaching)
    assert "not saved" in visible and teaching in visible
    assert context.extension("mastery")["profile_receipt"]["status"] == "not_saved"


@pytest.mark.parametrize("language, notice", [("en", "not saved"), ("zh", "未能保存")])
def test_unsaved_notice_preserves_card_finish_postcondition(language, notice):
    from deeptutor.capabilities.mastery.loop import MasteryLoopCapability
    from deeptutor.core.context import UnifiedContext

    context = UnifiedContext(language=language, metadata={"mastery_mode": True})
    context.extension("mastery").update(profile_write_pending=True, card_posted=True)
    visible = MasteryLoopCapability().final_text_override(context, "")
    assert notice in visible
    assert context.extension("mastery")["card_posted"] is False


@pytest.mark.parametrize("quiz_requested", [False, True])
def test_unsaved_profile_notice_does_not_finish_an_active_tool_round(quiz_requested):
    from deeptutor.capabilities.mastery.loop import MasteryLoopCapability
    from deeptutor.core.context import UnifiedContext

    context = UnifiedContext(metadata={"mastery_mode": True})
    capability = MasteryLoopCapability()
    state = context.extension("mastery")
    state.update(profile_write_pending=True, quiz_requested=quiz_requested)
    assert capability.final_text_override(context, "") is None
    assert state["profile_write_pending"] is True
    assert "profile_receipt" not in state
    if quiz_requested:
        state["profile_repair_requested"] = True
        assert "no question card" in capability.finish_instruction(context, "Done.")
        state["card_posted"] = True
        final = capability.final_text_override(context, "")
    else:
        final = capability.final_text_override(context, "Useful explanation.")
        assert final.endswith("Useful explanation.")
    assert "was not saved" in final
    assert state["profile_receipt"] == {"status": "not_saved"}


@pytest.mark.parametrize("updates", [None, []])
def test_profile_schema_accepts_absence_values(updates):
    import jsonschema

    schema = MasteryProfileTool().get_definition().to_openai_schema()["function"]["parameters"]
    jsonschema.validate({"preferences": "Project driven", "teaching_updates": updates}, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"teaching_updates": [None] * 7}, schema)


def test_evidence_cannot_span_separate_answers():
    from deeptutor.learning.teaching import parse_teaching_updates

    update = {
        "kind": "preference",
        "op": "upsert",
        "key": "style",
        "text": "Projects",
        "basis": "learner_report",
        "evidence": "Project driven",
    }
    with pytest.raises(ValueError, match="literal quote"):
        parse_teaching_updates([update], ("Project", " driven"))


@pytest.mark.asyncio
async def test_native_finish_policy_does_not_consume_repair_or_publish_a_notice_early():
    from deeptutor.agents.loop.native_adapter import NativeAdapter
    from deeptutor.agents.loop.pipeline import AgenticLoopPipeline
    from deeptutor.capabilities.mastery.loop import MasteryLoopCapability
    from deeptutor.core.context import UnifiedContext

    cap = MasteryLoopCapability()
    pipeline = object.__new__(AgenticLoopPipeline)
    pipeline._active_loop_capabilities = lambda _: [cap]
    context = UnifiedContext(metadata={"mastery_mode": True})
    state = context.extension("mastery")
    state["profile_write_pending"] = True
    adapter = NativeAdapter(pipeline, context, None, [])
    first = await adapter.invoke("policy", {"text": "A useful explanation"}, {})
    assert first["redirect"] and first["override"] is None
    assert state["profile_write_pending"] and "profile_repair_requested" not in state
    await adapter.invoke("finish_redirected", {}, {})
    final = await adapter.invoke("policy", {"text": "A useful explanation"}, {})
    assert not final["redirect"]
    assert "not saved" in final["override"]
    assert "A useful explanation" in final["override"]


@pytest.mark.asyncio
@pytest.mark.parametrize("engine", ["python", "native"])
async def test_running_user_messages_feed_the_same_evidence(engine):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from deeptutor.agents.loop.loop_host import AgentLoopHost
    from deeptutor.agents.loop.native_adapter import NativeAdapter
    from deeptutor.core.context import TurnRuntimeContext, UnifiedContext

    inputs = [{"command_id": "cmd", "content": "Actually, prefer diagrams"}]
    context = UnifiedContext(
        user_message="Explain this",
        metadata={"turn_id": "t", "mastery_path_id": "p"},
        runtime=TurnRuntimeContext(drain_user_inputs=lambda: inputs),
    )
    if engine == "native":
        result = await NativeAdapter(None, context, None, []).invoke("read_user_inputs", {}, {})
        assert result == inputs
    else:
        host = object.__new__(AgentLoopHost)
        host.context = context
        host.pipeline = SimpleNamespace(_t=lambda key, **kw: kw["default"])
        host.loop = SimpleNamespace(
            _append_loop_instruction=lambda *_: None, source="test", stage="test"
        )
        host.messages = []
        host.stream = SimpleNamespace(progress=AsyncMock())
        await host.read_inbox()
    assert context.user_evidence() == ("Explain this", "Actually, prefer diagrams")
    assert context.interaction.user_answers[0]["input_id"] == "cmd"
