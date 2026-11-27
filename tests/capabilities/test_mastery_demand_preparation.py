"""Preparation is demand-driven; cache misses are not missing subject matter."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from deeptutor.capabilities.mastery.pipeline import MasteryLoopPipeline
from deeptutor.core.context import UnifiedContext
from deeptutor.learning import lesson_evidence, policy, storage


@pytest.fixture
def preparation(monkeypatch):
    progress = SimpleNamespace(book_id="path", modules=[object()], lesson_evidence={})
    store = SimpleNamespace(load=Mock(return_value=progress), get_topic=Mock(return_value=object()))
    monkeypatch.setattr(storage, "LearningStore", lambda: store)
    monkeypatch.setattr(
        policy, "next_objective", lambda _: SimpleNamespace(knowledge_point_id="next")
    )
    monkeypatch.setattr(lesson_evidence, "objective_fingerprint", lambda *args: "current")
    scope = Mock(return_value={"selected": ["lesson.pdf"]})
    cache = Mock(return_value=None)
    paid = AsyncMock(side_effect=lesson_evidence.LessonUnavailable("Coverage incomplete"))
    monkeypatch.setattr(lesson_evidence, "selected_scope", scope)
    monkeypatch.setattr(lesson_evidence, "cached_lesson", cache)
    monkeypatch.setattr(lesson_evidence, "prepare_lesson", paid)
    stream = SimpleNamespace(sources=AsyncMock())
    pipeline = MasteryLoopPipeline(language="en")
    return SimpleNamespace(
        progress=progress,
        store=store,
        scope=scope,
        cache=cache,
        paid=paid,
        stream=stream,
        pipeline=pipeline,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "learner_message",
    [
        "Why did the outline order not change?",
        "Miért nem rendezted át a vázlatot?",
        "Continue the next lesson",
    ],
)
async def test_cache_miss_never_starts_automatic_paid_preparation(preparation, learner_message):
    context = UnifiedContext(user_message=learner_message, metadata={"mastery_path_id": "path"})
    messages = [
        {"role": "user", "content": learner_message},
        {"role": "tool", "content": "Earlier assessment already saved"},
    ]
    for _ in range(3):
        assert (
            await preparation.pipeline.prepare_model_request(context, preparation.stream, messages)
            == []
        )
    preparation.paid.assert_not_awaited()
    assert messages[0]["content"] == learner_message
    assert messages[1]["content"] == "Earlier assessment already saved"
    packets = [m for m in messages if m.get("_lesson_packet")]
    assert len(packets) == 1
    assert "mastery_prepare_lesson" in packets[0]["content"]
    assert "not prepared" in packets[0]["content"]
    assert "NOT conversation" in packets[0]["content"]
    assert "unavailable" not in packets[0]["content"]


@pytest.mark.asyncio
async def test_valid_packet_is_reused_without_new_preparation(preparation, monkeypatch):
    evidence = {"id": "verified", "sources": [{"ref": "one"}, {"ref": "two"}, {"ref": "three"}]}
    preparation.cache.return_value = evidence
    pixels = Mock(return_value={"role": "user", "content": "verified pixels"})
    monkeypatch.setattr(lesson_evidence, "image_message", pixels)
    monkeypatch.setattr(lesson_evidence, "lesson_context", lambda _: "VERIFIED ACTIVE LESSON")
    monkeypatch.setattr(lesson_evidence, "public_sources", lambda _: [])
    context = UnifiedContext(metadata={"mastery_path_id": "path"})
    messages = []
    for _ in range(2):
        assert await preparation.pipeline.prepare_model_request(
            context, preparation.stream, messages
        )
    preparation.paid.assert_not_awaited()
    assert pixels.call_count == 1
    assert pixels.call_args.args == (evidence["sources"][:2],)
    preparation.stream.sources.assert_not_awaited()
    assert len(messages) == 1 and messages[0]["content"] == "VERIFIED ACTIVE LESSON"


@pytest.mark.asyncio
async def test_stale_packet_offers_authorized_refresh_without_automatic_paid_work(preparation):
    preparation.cache.side_effect = lesson_evidence.LessonUnavailable("Selected sources changed")
    context = UnifiedContext(
        user_message="Continue the lesson", metadata={"mastery_path_id": "path"}
    )
    messages = []
    assert (
        await preparation.pipeline.prepare_model_request(context, preparation.stream, messages)
        == []
    )
    notice = messages[0]["content"]
    assert "mastery_prepare_lesson" in notice and '"knowledge_point_id": "next"' in notice
    assert "access denial" in notice and "unchanged" in notice
    preparation.paid.assert_not_awaited()


@pytest.mark.asyncio
async def test_cache_is_checked_again_after_state_changes(preparation, monkeypatch):
    preparation.cache.side_effect = [{"id": "first", "sources": []}, None]
    monkeypatch.setattr(lesson_evidence, "image_message", lambda _: {"content": "old pixels"})
    monkeypatch.setattr(lesson_evidence, "lesson_context", lambda _: "OLD VERIFIED PACKET")
    monkeypatch.setattr(lesson_evidence, "public_sources", lambda _: [])
    context = UnifiedContext(metadata={"mastery_path_id": "path"})
    messages = []
    assert await preparation.pipeline.prepare_model_request(context, preparation.stream, messages)
    assert (
        await preparation.pipeline.prepare_model_request(context, preparation.stream, messages)
        == []
    )
    assert preparation.pipeline._lesson_pixels is None
    assert "OLD VERIFIED PACKET" not in str(messages)
    assert "not prepared" in messages[-1]["content"]
    preparation.paid.assert_not_awaited()


@pytest.mark.asyncio
async def test_text_only_route_does_not_acquire_a_pdf_gate(preparation):
    preparation.scope.return_value = {}
    context = UnifiedContext(metadata={"mastery_path_id": "path"})
    messages = [{"role": "user", "content": "Explain a text-only subject"}]
    preparation.pipeline._lesson_pixels = ("previous", {"content": "old PDF"})
    assert (
        await preparation.pipeline.prepare_model_request(context, preparation.stream, messages)
        == []
    )
    assert len(messages) == 1
    assert preparation.pipeline._lesson_pixels is None
    preparation.paid.assert_not_awaited()


@pytest.mark.asyncio
async def test_removed_pdf_scope_is_not_a_text_only_fallback(preparation):
    preparation.scope.return_value = {}
    preparation.progress.lesson_evidence = {"next": {"id": "previous-source"}}
    context = UnifiedContext(metadata={"mastery_path_id": "path"})
    messages = []
    assert (
        await preparation.pipeline.prepare_model_request(context, preparation.stream, messages)
        == []
    )
    assert "materials have changed" in messages[-1]["content"]
    preparation.paid.assert_not_awaited()


@pytest.mark.asyncio
async def test_access_failure_is_reported_without_paid_recovery(preparation):
    preparation.scope.side_effect = lesson_evidence.LessonUnavailable(
        "Selected material access denied"
    )
    context = UnifiedContext(
        user_message="Explain the outline change", metadata={"mastery_path_id": "path"}
    )
    messages = [{"role": "user", "content": context.user_message}]
    assert (
        await preparation.pipeline.prepare_model_request(context, preparation.stream, messages)
        == []
    )
    assert "Selected material access denied" in messages[-1]["content"]
    assert "NOT conversation" in messages[-1]["content"]
    assert messages[0]["content"] == context.user_message
    preparation.paid.assert_not_awaited()


@pytest.mark.asyncio
async def test_outline_mode_does_not_load_or_prepare_lesson(preparation):
    context = UnifiedContext(
        metadata={"mastery_path_id": "path", "mastery_session_mode": "outline"}
    )
    assert await preparation.pipeline.prepare_model_request(context, preparation.stream, []) == []
    preparation.store.load.assert_not_called()
    preparation.paid.assert_not_awaited()


@pytest.mark.asyncio
async def test_prepare_tool_passes_focused_task_and_runtime_request(monkeypatch):
    from deeptutor.capabilities.mastery import tools
    from deeptutor.services.llm import config

    evidence = {"id": "packet", "coverage": {"complete": False, "missing": "One detail"}}
    prepare = AsyncMock(return_value=evidence)
    monkeypatch.setattr(tools, "_new_service", lambda: SimpleNamespace(store="store"))
    monkeypatch.setattr(lesson_evidence, "prepare_lesson", prepare)
    monkeypatch.setattr(lesson_evidence, "lesson_context", lambda _: "Teach the supported part")
    monkeypatch.setattr(lesson_evidence, "public_sources", lambda _: [])
    monkeypatch.setattr(config, "get_llm_config", lambda: "config")
    result = await tools.MasteryPrepareLessonTool().execute(
        _mastery_path_id="path",
        knowledge_point_id="objective",
        focus="Original practice questions about the taught comparison",
        _learner_message="Use the actual question bank, then a similar problem.",
        refresh=True,
    )
    assert result.success
    assert (
        prepare.call_args.kwargs["focus"]
        == "Original practice questions about the taught comparison"
    )
    assert (
        prepare.call_args.kwargs["learner_request"]
        == "Use the actual question bank, then a similar problem."
    )
    assert prepare.call_args.kwargs["refresh"] is True


@pytest.mark.asyncio
async def test_partial_packet_is_delivered_without_automatic_retry(preparation, monkeypatch):
    evidence = {
        "id": "partial",
        "sources": [],
        "coverage": {"complete": False, "missing": "One unverified detail"},
    }
    preparation.cache.return_value = evidence
    monkeypatch.setattr(lesson_evidence, "image_message", lambda _: {"content": "pixels"})
    monkeypatch.setattr(lesson_evidence, "public_sources", lambda _: [])
    context = UnifiedContext(user_message="Please continue", metadata={"mastery_path_id": "path"})
    messages = []
    await preparation.pipeline.prepare_model_request(context, preparation.stream, messages)
    assert "partial" in messages[-1]["content"].lower()
    assert "One unverified detail" in messages[-1]["content"]
    preparation.paid.assert_not_awaited()


@pytest.mark.asyncio
async def test_explicit_focus_is_runtime_bound_and_expires_when_policy_advances(
    preparation, monkeypatch
):
    from deeptutor.capabilities.mastery.loop import MasteryLoopCapability

    context = UnifiedContext(
        user_message="Explain the earlier objective",
        metadata={
            "mastery_mode": True,
            "mastery_path_id": "path",
        },
    )
    forged = Mock()
    bound = MasteryLoopCapability().augment_kwargs(
        "mastery_prepare_lesson", {"_bind_lesson_objective": forged}, context
    )
    bound["_bind_lesson_objective"]("reviewed")
    assert context.metadata["mastery_lesson_objective"] == {
        "path_id": "path",
        "kp_id": "reviewed",
        "policy_id": "next",
    }
    messages = []
    await preparation.pipeline.prepare_model_request(context, preparation.stream, messages)
    assert preparation.cache.call_args.args[2] == "reviewed"
    monkeypatch.setattr(
        policy, "next_objective", lambda _: SimpleNamespace(knowledge_point_id="advanced")
    )
    await preparation.pipeline.prepare_model_request(context, preparation.stream, messages)
    assert preparation.cache.call_args.args[2] == "advanced"
    forged.assert_not_called()
    preparation.paid.assert_not_awaited()


@pytest.mark.asyncio
async def test_historical_packet_refresh_preserves_archive_boundary_and_literal_user_text(
    preparation,
):
    context = UnifiedContext(metadata={"mastery_path_id": "path"})
    messages = [
        {"role": "user", "content": "old learner question"},
        {"role": "user", "content": "old packet", "_lesson_packet": True},
        {"role": "assistant", "content": "old explanation"},
        {"role": "user", "content": "I literally wrote old packet in my question"},
    ]
    preparation.pipeline._model_turn_start = 3
    await preparation.pipeline.prepare_model_request(context, preparation.stream, messages)
    assert preparation.pipeline._model_turn_start == 2
    assert messages[2]["content"] == "I literally wrote old packet in my question"
    assert len([m for m in messages if m.get("_lesson_packet")]) == 1
