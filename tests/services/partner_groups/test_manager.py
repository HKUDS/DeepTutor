from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.services.partner_groups.manager import LiveGroupTurn, PartnerGroupManager
from deeptutor.services.partner_groups.models import (
    GroupMessage,
    PartnerGroupConfig,
    PartnerInvocation,
    utc_now,
)
from deeptutor.services.partner_groups.modes import DiscussionContext, PanelParallelMode
from deeptutor.services.partner_groups.store import (
    PUBLIC_TRANSCRIPT_MAX_CHARS,
    GroupTranscriptStore,
    PartnerInvocationStore,
)
from deeptutor.services.partners.manager import (
    PartnerConfig,
    PartnerGroupTurnResponse,
    PartnerManager,
)


@pytest.fixture
def partners_root(tmp_path, monkeypatch):
    """Keep both global Partners and user-scoped Group files under tmp_path."""
    from deeptutor.multi_user import paths

    admin_root = (tmp_path / "data").resolve()
    monkeypatch.setattr(paths, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(paths, "ADMIN_WORKSPACE_ROOT", admin_root)
    monkeypatch.setattr(paths, "USERS_ROOT", admin_root / "users")
    monkeypatch.setattr(paths, "SYSTEM_ROOT", admin_root / "system")
    monkeypatch.setattr(paths, "_path_services", {})
    admin_root.mkdir(parents=True, exist_ok=True)
    from deeptutor.multi_user.context import reset_current_user, set_current_user
    from deeptutor.multi_user.models import CurrentUser, UserScope

    token = set_current_user(
        CurrentUser(
            id="test-admin",
            username="test-admin",
            role="admin",
            scope=UserScope(kind="admin", user_id="test-admin", root=admin_root),
        )
    )
    try:
        yield admin_root / "partners"
    finally:
        reset_current_user(token)


@pytest.fixture
def group_runtime(partners_root, monkeypatch):
    import deeptutor.services.partner_groups.manager as group_manager_module

    partners = PartnerManager()
    partners.save_config("socrates", PartnerConfig(name="Socrates", emoji="🏛️"))
    partners.save_config("feynman", PartnerConfig(name="Feynman", emoji="🔬"))
    monkeypatch.setattr(group_manager_module, "get_partner_manager", lambda: partners)
    monkeypatch.setattr(
        partners,
        "get_partner",
        lambda partner_id: SimpleNamespace(running=True, partner_id=partner_id),
    )
    manager = PartnerGroupManager()
    group = manager.create_group(
        name="Learning panel",
        member_ids=["socrates", "feynman"],
    )
    return manager, partners, group


def test_no_mention_means_all_and_mentions_are_structured(group_runtime) -> None:
    manager, _partners, group = group_runtime
    assert list(manager.resolve_mentions(group, "Explain entropy", None).targets) == [
        "socrates",
        "feynman",
    ]
    assert list(manager.resolve_mentions(group, "@Socrates challenge this", None).targets) == [
        "socrates"
    ]
    assert list(manager.resolve_mentions(group, "@socrates @feynman compare", None).targets) == [
        "socrates",
        "feynman",
    ]
    partial = manager.resolve_mentions(group, "@socrates @missing answer", None)
    assert list(partial.targets) == ["socrates"]
    assert list(partial.unknown_mentions) == ["@missing"]
    fallback = manager.resolve_mentions(group, "@missing: answer", None)
    assert list(fallback.targets) == ["socrates", "feynman"]
    assert list(fallback.unknown_mentions) == ["@missing"]


def test_group_creation_validates_memory_without_cross_group_storage(group_runtime) -> None:
    manager, _partners, group = group_runtime

    assert not (manager.store.root / "shared").exists()
    assert not (manager.store.group_dir(group.group_id) / "shared").exists()


def test_list_groups_explicitly_excludes_another_owner(group_runtime) -> None:
    manager, _partners, group = group_runtime
    foreign_dir = manager.store.group_dir("foreign")
    foreign_dir.mkdir(parents=True)
    foreign = PartnerGroupConfig(
        group_id="foreign",
        owner_id="another-user",
        name="Foreign",
        member_ids=list(group.member_ids),
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    (foreign_dir / "config.json").write_text(
        json.dumps(foreign.to_dict()),
        encoding="utf-8",
    )

    assert [item["group_id"] for item in manager.list_groups()] == [group.group_id]


@pytest.mark.asyncio
async def test_parallel_panel_shares_snapshot_and_only_persists_final_messages(
    group_runtime, monkeypatch
) -> None:
    manager, partners, group = group_runtime
    calls: list[tuple[str, str, str]] = []
    entered: set[str] = set()
    both_entered = asyncio.Event()

    async def send_group_message(partner_id, content, **kwargs):
        entered.add(partner_id)
        if len(entered) == 2:
            both_entered.set()
        await asyncio.wait_for(both_entered.wait(), timeout=1)
        calls.append((partner_id, content, kwargs["public_context"]))
        return f"{partner_id} final answer"

    monkeypatch.setattr(partners, "send_group_message", send_group_message)
    frames: list[dict] = []

    async def emit(frame: dict) -> None:
        frames.append(frame)

    result = await manager.send_message(
        group.group_id,
        content="How should I study this?",
        session_key="session-a",
        emit=emit,
    )

    assert result.targets == ["socrates", "feynman"]
    assert {reply.author_id for reply in result.replies} == {"socrates", "feynman"}
    assert len(calls) == 2
    assert calls[0][1] == calls[1][1] == "How should I study this?"
    expected_context = (
        "Group: Learning panel\n"
        "Parallel panel members and positioning:\n"
        "- Socrates (@socrates)\n"
        "- Feynman (@feynman)\n\n"
        "Public transcript before the current message:\n"
        "(empty)"
    )
    assert calls[0][2] == calls[1][2] == expected_context
    assert all("How should I study this?" not in context for _, _, context in calls)
    assert manager.whiteboard(group.group_id) == []
    history = manager.history(group.group_id, "session-a")
    assert [item["role"] for item in history] == ["user", "partner", "partner"]
    assert {frame["type"] for frame in frames} == {
        "user_message",
        "partner_started",
        "partner_message",
        "done",
    }
    assert all("event" not in item for item in history)


@pytest.mark.asyncio
async def test_parallel_panel_calls_responder_without_optional_kwargs(group_runtime) -> None:
    _manager, _partners, group = group_runtime
    calls: list[str] = []

    async def positional_responder(partner_id: str) -> GroupMessage:
        calls.append(partner_id)
        return GroupMessage(
            event_id=partner_id,
            turn_id="turn",
            session_key="session",
            role="partner",
            content=f"{partner_id} answer",
            author_id=partner_id,
            author_name=partner_id,
            created_at=utc_now(),
        )

    messages = await PanelParallelMode().run(
        DiscussionContext(
            group=group,
            targets=list(group.member_ids),
            respond=positional_responder,
            emit=lambda frame: _append([], frame),
        )
    )

    assert set(calls) == {"socrates", "feynman"}
    assert [message.content for message in messages] == [
        "socrates answer",
        "feynman answer",
    ]


@pytest.mark.asyncio
async def test_sequential_mode_uses_member_order_and_only_prior_round_messages(
    group_runtime, monkeypatch
) -> None:
    manager, partners, group = group_runtime
    manager.update_group(group.group_id, {"discussion_mode": "sequential"})
    calls: list[tuple[str, str, str]] = []

    async def send_group_message(partner_id, content, **kwargs):
        calls.append((partner_id, content, kwargs["public_context"]))
        return f"{partner_id} distinct contribution"

    monkeypatch.setattr(partners, "send_group_message", send_group_message)
    frames: list[dict] = []
    result = await manager.send_message(
        group.group_id,
        content="Build a study plan",
        session_key="sequential-session",
        mentions=["feynman", "socrates"],
        emit=lambda frame: _append(frames, frame),
    )

    assert result.targets == ["feynman", "socrates"]
    assert [reply.author_id for reply in result.replies] == ["socrates", "feynman"]
    assert [call[0] for call in calls] == ["socrates", "feynman"]
    assert "Messages already produced this round:" not in calls[0][2]
    assert calls[1][2].endswith(
        "Messages already produced this round:\nSocrates: socrates distinct contribution"
    )
    assert "feynman distinct contribution" not in calls[1][2]
    assert "applies only to @socrates's upcoming turn" in calls[0][1]
    assert "applies only to @feynman's upcoming turn" in calls[1][1]
    assert "do not repeat what has already been said" in calls[1][1]
    assert [frame["type"] for frame in frames] == [
        "user_message",
        "partner_started",
        "partner_message",
        "partner_started",
        "partner_message",
        "done",
    ]
    history = manager.history(group.group_id, "sequential-session")
    assert [message["kind"] for message in history] == ["message", "message", "message"]
    persisted = json.dumps(history)
    assert "Messages already produced this round" not in persisted
    assert "upcoming_partner_turn_requirement" not in persisted


@pytest.mark.asyncio
async def test_debate_mode_runs_two_parallel_rounds_with_distinct_kinds(
    group_runtime, monkeypatch
) -> None:
    manager, partners, group = group_runtime
    manager.update_group(group.group_id, {"discussion_mode": "debate"})
    opening_entered: set[str] = set()
    clash_entered: set[str] = set()
    openings_ready = asyncio.Event()
    clashes_ready = asyncio.Event()
    calls: list[tuple[str, str, str, str]] = []

    async def send_group_message(partner_id, content, **kwargs):
        if "debate's opening statement" in content:
            phase = "opening"
            opening_entered.add(partner_id)
            if len(opening_entered) == 2:
                openings_ready.set()
            await asyncio.wait_for(openings_ready.wait(), timeout=1)
        else:
            phase = "clash"
            clash_entered.add(partner_id)
            if len(clash_entered) == 2:
                clashes_ready.set()
            await asyncio.wait_for(clashes_ready.wait(), timeout=1)
        calls.append((phase, partner_id, content, kwargs["public_context"]))
        return f"{partner_id} {phase}"

    monkeypatch.setattr(partners, "send_group_message", send_group_message)
    frames: list[dict] = []
    result = await manager.send_message(
        group.group_id,
        content="Correct errors first or encourage first?",
        session_key="debate-session",
        emit=lambda frame: _append(frames, frame),
    )

    assert opening_entered == clash_entered == {"socrates", "feynman"}
    assert [reply.kind for reply in result.replies] == [
        "message",
        "message",
        "debate_rebuttal",
        "debate_rebuttal",
    ]
    opening_calls = [call for call in calls if call[0] == "opening"]
    clash_calls = [call for call in calls if call[0] == "clash"]
    assert len(opening_calls) == len(clash_calls) == 2
    assert opening_calls[0][3] == opening_calls[1][3]
    assert "Messages already produced this round:" not in opening_calls[0][3]
    assert clash_calls[0][3] == clash_calls[1][3]
    assert "Socrates: socrates opening" in clash_calls[0][3]
    assert "Feynman: feynman opening" in clash_calls[0][3]
    assert all("Do not restate your own Round 1 content" in call[2] for call in clash_calls)
    assert all("argue for" not in call[2].lower() for call in calls)
    assert all("argue against" not in call[2].lower() for call in calls)
    partner_frames = [frame for frame in frames if frame["type"] == "partner_message"]
    assert [frame["message"]["kind"] for frame in partner_frames[:2]] == [
        "message",
        "message",
    ]
    assert [frame["message"]["kind"] for frame in partner_frames[2:]] == [
        "debate_rebuttal",
        "debate_rebuttal",
    ]
    history = manager.history(group.group_id, "debate-session")
    assert {message["turn_id"] for message in history} == {result.turn_id}
    assert [message["kind"] for message in history] == [
        "message",
        "message",
        "message",
        "debate_rebuttal",
        "debate_rebuttal",
    ]


@pytest.mark.asyncio
async def test_round_summary_receives_whole_round_and_can_repeat_with_another_member(
    group_runtime, monkeypatch
) -> None:
    manager, partners, group = group_runtime

    async def answer_round(partner_id, content, **kwargs):
        _ = (content, kwargs)
        return f"{partner_id} answer"

    monkeypatch.setattr(partners, "send_group_message", answer_round)
    turn = await manager.send_message(
        group.group_id,
        content="Which learning strategy is strongest?",
        session_key="summary-session",
    )
    summary_calls: list[tuple[str, str, str, bool]] = []

    async def answer_summary(partner_id, content, **kwargs):
        summary_calls.append(
            (partner_id, content, kwargs["public_context"], kwargs["allow_invoke_other"])
        )
        await kwargs["on_event"](
            StreamEvent(type=StreamEventType.CONTENT, content=f"{partner_id} summary trace")
        )
        return f"{partner_id} three-section summary"

    monkeypatch.setattr(partners, "send_group_message", answer_summary)
    first_frames: list[dict] = []
    first = await manager.summarize_round(
        group.group_id,
        turn.turn_id,
        session_key="summary-session",
        partner_id="socrates",
        emit=lambda frame: _append(first_frames, frame),
    )
    second_frames: list[dict] = []
    second = await manager.summarize_round(
        group.group_id,
        turn.turn_id,
        session_key="summary-session",
        partner_id="feynman",
        emit=lambda frame: _append(second_frames, frame),
    )

    assert first.kind == second.kind == "round_summary"
    assert first.turn_id == second.turn_id == turn.turn_id
    assert [call[0] for call in summary_calls] == ["socrates", "feynman"]
    assert all(call[3] is False for call in summary_calls)
    for call in summary_calls:
        assert "Messages already produced this round:" in call[2]
        assert "test-admin: Which learning strategy is strongest?" in call[2]
        assert "Socrates: socrates answer" in call[2]
        assert "Feynman: feynman answer" in call[2]
        assert "exactly three clearly labeled sections" in call[1]
    assert "socrates three-section summary" not in summary_calls[1][2]
    assert [frame["type"] for frame in first_frames] == [
        "partner_started",
        "partner_trace",
        "partner_message",
        "done",
    ]
    assert [frame["type"] for frame in second_frames] == [
        "partner_started",
        "partner_trace",
        "partner_message",
        "done",
    ]
    assert first_frames[-1]["result"] == {
        "operation": "summarize_round",
        "turn_id": turn.turn_id,
        "partner_id": "socrates",
        "message": first.to_dict(),
    }
    history = manager.history(group.group_id, "summary-session")
    assert [message["kind"] for message in history] == [
        "message",
        "message",
        "message",
        "round_summary",
        "round_summary",
    ]
    persisted = json.dumps(history)
    assert "upcoming_partner_turn_requirement" not in persisted
    with pytest.raises(ValueError, match="not a current Group member"):
        await manager.summarize_round(
            group.group_id,
            turn.turn_id,
            session_key="summary-session",
            partner_id="missing",
        )
    with pytest.raises(LookupError, match="round not found"):
        await manager.summarize_round(
            group.group_id,
            "missing-turn",
            session_key="summary-session",
            partner_id="socrates",
        )


@pytest.mark.asyncio
async def test_turn_reuses_one_member_snapshot_and_does_not_reinject_whiteboard(
    group_runtime, monkeypatch
) -> None:
    manager, partners, group = group_runtime
    original_load = partners.load_config
    loads: list[str] = []
    contexts: list[str] = []

    def counted_load(partner_id: str):
        loads.append(partner_id)
        return original_load(partner_id)

    async def send_group_message(partner_id, content, **kwargs):
        _ = (partner_id, content)
        contexts.append(kwargs["public_context"])
        return "distinct answer"

    monkeypatch.setattr(partners, "load_config", counted_load)
    monkeypatch.setattr(partners, "send_group_message", send_group_message)
    await manager.send_message(
        group.group_id,
        content="first public question",
        session_key="snapshot-session",
    )
    assert loads == ["socrates", "feynman"]

    loads.clear()
    contexts.clear()
    result = await manager.send_message(
        group.group_id,
        content="second public question",
        session_key="snapshot-session",
        mentions=["socrates", "typo"],
    )

    assert loads == ["socrates", "feynman"]
    assert result.unknown_mentions == ["@typo"]
    assert len(contexts) == 1
    assert contexts[0].count("first public question") == 1
    assert "Shared whiteboard" not in contexts[0]
    assert "coding" not in contexts[0]


@pytest.mark.asyncio
async def test_partial_partner_failure_does_not_cancel_panel(group_runtime, monkeypatch) -> None:
    manager, partners, group = group_runtime

    async def send_group_message(partner_id, content, **kwargs):
        _ = (content, kwargs)
        if partner_id == "socrates":
            raise RuntimeError("model unavailable")
        return "successful final"

    monkeypatch.setattr(partners, "send_group_message", send_group_message)
    result = await manager.send_message(
        group.group_id,
        content="Debate this",
        session_key="session-b",
    )
    by_id = {reply.author_id: reply for reply in result.replies}
    assert by_id["socrates"].error is True
    assert by_id["feynman"].content == "successful final"
    assert by_id["feynman"].error is False


@pytest.mark.asyncio
async def test_retry_replaces_only_the_failed_seat_in_the_original_turn(
    group_runtime, monkeypatch
) -> None:
    manager, partners, group = group_runtime

    async def first_attempt(partner_id, content, **kwargs):
        _ = (content, kwargs)
        if partner_id == "socrates":
            raise RuntimeError("temporary model failure")
        return "parallel answer must stay private from the retry"

    monkeypatch.setattr(partners, "send_group_message", first_attempt)
    original = await manager.send_message(
        group.group_id,
        content="Debate this",
        session_key="retry-session",
    )
    failed = next(reply for reply in original.replies if reply.author_id == "socrates")
    contexts: list[str] = []

    async def retry_attempt(partner_id, content, **kwargs):
        assert partner_id == "socrates"
        assert content == "Debate this"
        contexts.append(kwargs["public_context"])
        await kwargs["on_event"](StreamEvent(type=StreamEventType.CONTENT, content="retry trace"))
        return PartnerGroupTurnResponse(content="recovered answer")

    monkeypatch.setattr(partners, "send_group_message", retry_attempt)
    frames: list[dict] = []
    replacement = await manager.retry_partner(
        group.group_id,
        original.turn_id,
        "socrates",
        session_key="retry-session",
        emit=lambda frame: _append(frames, frame),
    )

    assert replacement.event_id == failed.event_id
    assert replacement.turn_id == original.turn_id
    assert replacement.error is False
    assert "Debate this" not in contexts[0]
    assert "parallel answer must stay private" not in contexts[0]
    history = manager.history(group.group_id, "retry-session")
    assert len(history) == 3
    assert next(row for row in history if row["author_id"] == "socrates")["content"] == (
        "recovered answer"
    )
    assert [frame["type"] for frame in frames] == [
        "partner_started",
        "partner_trace",
        "partner_message",
        "done",
    ]
    assert all(frame.get("turn_id", original.turn_id) == original.turn_id for frame in frames)
    with pytest.raises(ValueError, match="failed Partner seat"):
        await manager.retry_partner(
            group.group_id,
            original.turn_id,
            "socrates",
            session_key="retry-session",
        )


@pytest.mark.asyncio
async def test_live_group_turn_replays_after_socket_detach(group_runtime, monkeypatch) -> None:
    manager, _partners, group = group_runtime
    release = asyncio.Event()

    async def send_message(group_id, *, emit, **kwargs):
        _ = (group_id, kwargs)
        await emit({"type": "user_message", "message": {"event_id": "u1"}})
        await release.wait()
        await emit({"type": "partner_message", "message": {"event_id": "p1"}})
        await emit({"type": "done", "result": {}})

    monkeypatch.setattr(manager, "send_message", send_message)
    live = manager.start_live_turn(
        group.group_id,
        content="question",
        session_key="live-session",
    )
    assert (
        manager.start_live_turn(
            group.group_id,
            content="question",
            session_key="live-session",
        )
        is live
    )
    with pytest.raises(ValueError, match="already in progress"):
        manager.start_live_turn(
            group.group_id,
            content="different question",
            session_key="live-session",
        )
    first = live.subscribe()
    assert (await asyncio.wait_for(first.get(), timeout=1))["type"] == "user_message"
    live.unsubscribe(first)  # the browser disconnected; the task must continue

    release.set()
    assert live.task is not None
    await asyncio.wait_for(live.task, timeout=1)
    replay = manager.subscribe_live_turn(group.group_id, "live-session")
    assert replay is live
    queue = replay.subscribe()
    assert [queue.get_nowait()["type"] for _ in range(queue.qsize())] == [
        "user_message",
        "partner_message",
        "done",
    ]


@pytest.mark.asyncio
async def test_cancel_cleans_active_turn_and_keeps_completed_answers(
    group_runtime, monkeypatch
) -> None:
    manager, partners, group = group_runtime
    never = asyncio.Event()

    async def send_group_message(partner_id, content, **kwargs):
        _ = (content, kwargs)
        if partner_id == "feynman":
            await never.wait()
        return f"{partner_id} completed"

    monkeypatch.setattr(partners, "send_group_message", send_group_message)
    live = manager.start_live_turn(
        group.group_id,
        content="cancel after one answer",
        session_key="cancel-session",
    )
    queue = live.subscribe()
    while True:
        frame = await asyncio.wait_for(queue.get(), timeout=1)
        if frame.get("type") == "partner_message":
            break

    assert frame["message"]["author_id"] == "socrates"
    manager.cancel_live_turn(group.group_id, "cancel-session")
    assert live.task is not None
    with pytest.raises(asyncio.CancelledError):
        await live.task
    await asyncio.sleep(0)

    while True:
        terminal = await asyncio.wait_for(queue.get(), timeout=1)
        if terminal["type"] == "cancelled":
            break
    assert manager._live_turns == {}
    assert manager.subscribe_live_turn(group.group_id, "cancel-session") is live
    history = manager.history(group.group_id, "cancel-session")
    assert [row["content"] for row in history] == [
        "cancel after one answer",
        "socrates completed",
        "",
    ]
    marker = history[-1]
    assert marker == {
        "event_id": marker["event_id"],
        "turn_id": live.turn_id,
        "session_key": "cancel-session",
        "role": "system",
        "content": "",
        "author_id": "system",
        "author_name": "System",
        "created_at": marker["created_at"],
        "mentions": [],
        "error": False,
        "kind": "round_stopped",
        "events": [],
        "invocation_id": "",
        "invocation": None,
    }
    assert len(marker["event_id"]) == 32


@pytest.mark.asyncio
async def test_live_replay_frames_and_completed_turns_are_bounded(
    group_runtime, monkeypatch
) -> None:
    manager, _partners, group = group_runtime
    live = LiveGroupTurn()
    for index in range(600):
        await live.emit({"type": "partner_trace", "index": index})
    assert len(live.frames) == 512
    assert live.frames[0]["index"] == 88

    async def send_message(group_id, *, emit, **kwargs):
        _ = (group_id, kwargs)
        await emit({"type": "done", "result": {}})

    monkeypatch.setattr(manager, "send_message", send_message)
    for index in range(70):
        turn = manager.start_live_turn(
            group.group_id,
            content=f"question {index}",
            session_key=f"bounded-{index}",
        )
        assert turn.task is not None
        await turn.task
    await asyncio.sleep(0)
    assert not manager._live_turns
    assert len(manager._completed_turns) == 64


@pytest.mark.asyncio
async def test_invocation_can_start_while_panel_turn_is_running(group_runtime, monkeypatch) -> None:
    manager, _partners, group = group_runtime
    main_started = asyncio.Event()
    invocation_started = asyncio.Event()
    wait_forever = asyncio.Event()

    async def send_message(group_id, **kwargs):
        _ = (group_id, kwargs)
        main_started.set()
        await wait_forever.wait()

    async def approve_invocation(group_id, invocation_id, **kwargs):
        _ = (group_id, invocation_id, kwargs)
        invocation_started.set()
        await wait_forever.wait()

    monkeypatch.setattr(manager, "send_message", send_message)
    monkeypatch.setattr(manager, "approve_invocation", approve_invocation)
    session_key = "concurrent-approval"
    invocation = PartnerInvocation(
        invocation_id=uuid4().hex,
        group_id=group.group_id,
        session_key=session_key,
        parent_turn_id=uuid4().hex,
        requester_partner_id="socrates",
        requester_partner_name="Socrates",
        target_partner_id="feynman",
        target_partner_name="Feynman",
        question="What would you test?",
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    PartnerInvocationStore(manager.store.group_dir(group.group_id)).save(invocation)

    main = manager.start_live_turn(
        group.group_id,
        content="panel still running",
        session_key=session_key,
    )
    await asyncio.wait_for(main_started.wait(), timeout=1)
    followup = manager.start_live_invocation(
        group.group_id,
        invocation_id=invocation.invocation_id,
        session_key=session_key,
    )
    await asyncio.wait_for(invocation_started.wait(), timeout=1)
    assert {id(item) for item in manager.subscribe_live_turns(group.group_id, session_key)} == {
        id(main),
        id(followup),
    }

    manager.cancel_live_turn(
        group.group_id,
        session_key,
        invocation_id=invocation.invocation_id,
    )
    manager.cancel_live_turn(group.group_id, session_key)
    assert main.task is not None and followup.task is not None
    await asyncio.gather(main.task, followup.task, return_exceptions=True)


@pytest.mark.asyncio
async def test_partner_trace_is_owner_visible_but_excluded_from_public_context(
    group_runtime, monkeypatch
) -> None:
    manager, partners, group = group_runtime
    private_event = StreamEvent(
        type=StreamEventType.THINKING,
        content="private scratch path",
        metadata={"call_id": "think-1"},
    )

    async def send_group_message(partner_id, content, **kwargs):
        assert partner_id == "socrates"
        await kwargs["on_event"](private_event)
        return PartnerGroupTurnResponse(
            content="Socrates final",
            events=[private_event.to_dict()],
        )

    monkeypatch.setattr(partners, "send_group_message", send_group_message)
    frames: list[dict] = []

    async def emit(frame: dict) -> None:
        frames.append(frame)

    await manager.send_message(
        group.group_id,
        content="@socrates answer",
        session_key="trace-session",
        emit=emit,
    )

    trace = next(frame for frame in frames if frame["type"] == "partner_trace")
    assert trace["partner_id"] == "socrates"
    assert trace["event"]["content"] == "private scratch path"
    history = manager.history(group.group_id, "trace-session")
    assert history[-1]["events"][0]["content"] == "private scratch path"

    from deeptutor.services.partner_groups.store import GroupTranscriptStore

    # The public render path deliberately ignores the persisted event payload.
    rendered = GroupTranscriptStore(manager.store.group_dir(group.group_id)).render("trace-session")
    assert "Socrates final" in rendered
    assert "private scratch path" not in rendered
    referenced, title = manager.referenced_transcript(
        group.group_id,
        "trace-session",
        language="en",
    )
    assert "Socrates: Socrates final" in referenced
    assert "private scratch path" not in referenced
    assert title.startswith("Learning panel:")


@pytest.mark.asyncio
async def test_invoke_other_requires_approval_then_adds_one_public_followup(
    group_runtime, monkeypatch
) -> None:
    manager, partners, group = group_runtime
    source_trace = StreamEvent(
        type=StreamEventType.THINKING,
        content="source private trace",
    )
    target_trace = StreamEvent(
        type=StreamEventType.THINKING,
        content="target private trace",
    )
    calls: list[tuple[str, dict]] = []

    async def send_group_message(partner_id, content, **kwargs):
        calls.append((partner_id, kwargs))
        if partner_id == "socrates":
            await kwargs["on_event"](source_trace)
            return PartnerGroupTurnResponse(
                content="My formal answer",
                events=[source_trace.to_dict()],
                invocation={
                    "target_partner_id": "feynman",
                    "target_partner_name": "Feynman",
                    "question": "Which assumption would you test first?",
                },
            )
        assert kwargs["allow_invoke_other"] is False
        assert "My formal answer" in kwargs["public_context"]
        assert "source private trace" not in kwargs["public_context"]
        await kwargs["on_event"](target_trace)
        return PartnerGroupTurnResponse(
            content="I would test the boundary case.",
            events=[target_trace.to_dict()],
            # Even a compromised/misbehaving invoked runner cannot make the
            # orchestrator persist a second hop.
            invocation={
                "target_partner_id": "socrates",
                "target_partner_name": "Socrates",
                "question": "This chained proposal must be ignored.",
            },
        )

    monkeypatch.setattr(partners, "send_group_message", send_group_message)
    first_frames: list[dict] = []
    await manager.send_message(
        group.group_id,
        content="@socrates evaluate this",
        session_key="invoke-session",
        emit=lambda frame: _append(first_frames, frame),
    )
    history = manager.history(group.group_id, "invoke-session")
    proposal = history[-1]["invocation"]
    assert proposal["status"] == "pending"
    assert len(calls) == 1, "the target must not run before user approval"

    followup_frames: list[dict] = []
    await manager.approve_invocation(
        group.group_id,
        proposal["invocation_id"],
        session_key="invoke-session",
        emit=lambda frame: _append(followup_frames, frame),
    )
    assert [frame["type"] for frame in followup_frames] == [
        "invocation_updated",
        "partner_message",
        "partner_started",
        "partner_trace",
        "partner_message",
        "invocation_updated",
        "done",
    ]
    assert len(calls) == 2
    history = manager.history(group.group_id, "invoke-session")
    assert [message["kind"] for message in history[-2:]] == [
        "invocation_question",
        "invocation_reply",
    ]
    assert history[-2]["content"] == "Which assumption would you test first?"
    assert history[-1]["content"] == "I would test the boundary case."
    assert history[-3]["invocation"]["status"] == "completed"
    invocations = manager.invocations(group.group_id, "invoke-session")
    assert len(invocations) == 1
    assert invocations[0]["question"] == "Which assumption would you test first?"
    assert manager.whiteboard(group.group_id) == []


@pytest.mark.asyncio
async def test_whiteboard_accepts_only_explicit_pins_and_enters_shared_context(
    group_runtime, monkeypatch
) -> None:
    manager, partners, group = group_runtime
    contexts: list[str] = []

    async def send_group_message(partner_id, content, **kwargs):
        _ = (partner_id, content)
        contexts.append(kwargs["public_context"])
        return "a public insight"

    monkeypatch.setattr(partners, "send_group_message", send_group_message)
    first = await manager.send_message(
        group.group_id,
        content="first question",
        session_key="curated",
        mentions=["socrates"],
    )
    legacy_path = manager.store.group_dir(group.group_id) / "shared" / "whiteboard.jsonl"
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path.write_text(
        json.dumps({"entry_id": "legacy", "content": "automatic legacy noise"}) + "\n",
        encoding="utf-8",
    )
    assert manager.whiteboard(group.group_id) == []

    pinned = manager.pin_whiteboard(group.group_id, first.replies[0].event_id)
    assert pinned["created"] is True
    assert pinned["entry"] == {
        "schema_version": 2,
        "kind": "pin",
        "event_id": first.replies[0].event_id,
        "turn_id": first.turn_id,
        "session_key": "curated",
        "author_id": "socrates",
        "author_name": "Socrates",
        "content": "a public insight",
        "created_at": first.replies[0].created_at,
        "pinned_at": pinned["entry"]["pinned_at"],
    }
    assert manager.pin_whiteboard(group.group_id, first.replies[0].event_id)["created"] is False

    contexts.clear()
    await manager.send_message(
        group.group_id,
        content="second question",
        session_key="curated",
        mentions=["socrates"],
    )
    assert "User-curated shared whiteboard" in contexts[0]
    assert contexts[0].count("a public insight") == 2  # transcript + one explicit pin
    assert "automatic legacy noise" not in contexts[0]

    assert manager.unpin_whiteboard(group.group_id, first.replies[0].event_id) is True
    assert manager.whiteboard(group.group_id) == []
    assert manager.unpin_whiteboard(group.group_id, first.replies[0].event_id) is False


def test_group_sessions_are_server_owned_and_delete_cascades_invocations(
    group_runtime,
) -> None:
    manager, _partners, group = group_runtime
    group_dir = manager.store.group_dir(group.group_id)
    transcript = GroupTranscriptStore(group_dir)
    session = manager.create_session(group.group_id)
    assert session["session_key"].startswith("pg-")
    assert session["title"] == ""
    assert session["message_count"] == 0
    assert session["created_at"]
    assert session["updated_at"] == session["created_at"]

    message = GroupMessage(
        event_id=uuid4().hex,
        turn_id=uuid4().hex,
        session_key=session["session_key"],
        role="user",
        content="  First   server-owned discussion  ",
        author_id="test-admin",
        author_name="test-admin",
        created_at=utc_now(),
    )
    transcript.append(message)
    manager.pin_whiteboard(group.group_id, message.event_id)
    invocation = manager.create_invocation(
        group.group_id,
        session_key=session["session_key"],
        requester_partner_id="socrates",
        target_partner_id="feynman",
        question="What should we verify?",
    )
    retained_invocation = manager.create_invocation(
        group.group_id,
        session_key="another-session",
        requester_partner_id="feynman",
        target_partner_id="socrates",
        question="What should remain?",
    )

    listed = manager.list_sessions(group.group_id)
    summary = next(item for item in listed if item["session_key"] == session["session_key"])
    assert summary["title"] == "First server-owned discussion"
    assert summary["message_count"] == 1
    assert summary["created_at"] == message.created_at
    assert summary["updated_at"] == message.created_at

    assert manager.delete_session(group.group_id, session["session_key"]) is True
    assert [item["event_id"] for item in manager.whiteboard(group.group_id)] == [message.event_id]
    assert manager.invocations(group.group_id, session["session_key"]) == []
    assert manager.invocations(group.group_id, "another-session") == [retained_invocation.to_dict()]
    assert invocation.invocation_id
    assert manager.history(group.group_id, session["session_key"]) == []
    assert manager.delete_session(group.group_id, session["session_key"]) is False


def test_transcript_session_summaries_use_recorded_keys_and_message_timestamps(
    tmp_path: Path,
) -> None:
    transcript = GroupTranscriptStore(tmp_path)
    older_key = "topic:alpha?"
    newer_key = "topic:beta?"
    transcript.append(
        GroupMessage(
            event_id=uuid4().hex,
            turn_id=uuid4().hex,
            session_key=older_key,
            role="partner",
            content="Opening context",
            author_id="socrates",
            author_name="Socrates",
            created_at="2026-01-01T00:00:00+00:00",
        )
    )
    transcript.append(
        GroupMessage(
            event_id=uuid4().hex,
            turn_id=uuid4().hex,
            session_key=older_key,
            role="user",
            content="  This   title is deliberately longer than forty characters total  ",
            author_id="test-admin",
            author_name="test-admin",
            created_at="2026-01-01T00:01:00+00:00",
        )
    )
    transcript.append(
        GroupMessage(
            event_id=uuid4().hex,
            turn_id=uuid4().hex,
            session_key=newer_key,
            role="partner",
            content="No user message here",
            author_id="feynman",
            author_name="Feynman",
            created_at="2026-01-02T00:00:00+00:00",
        )
    )

    summaries = [item.to_dict() for item in transcript.list_sessions()]

    assert summaries == [
        {
            "session_key": newer_key,
            "title": "",
            "message_count": 1,
            "updated_at": "2026-01-02T00:00:00+00:00",
            "created_at": "2026-01-02T00:00:00+00:00",
        },
        {
            "session_key": older_key,
            "title": "This title is deliberately longer than f",
            "message_count": 2,
            "updated_at": "2026-01-01T00:01:00+00:00",
            "created_at": "2026-01-01T00:00:00+00:00",
        },
    ]


def test_listing_sessions_does_not_create_a_missing_directory(tmp_path: Path) -> None:
    transcript = GroupTranscriptStore(tmp_path)

    assert transcript.list_sessions() == []
    assert not transcript.directory.exists()


@pytest.mark.parametrize(
    ("requester", "target", "question", "message"),
    [
        ("missing", "feynman", "Question", "Requester Partner"),
        ("socrates", "missing", "Question", "Target Partner"),
        ("socrates", "socrates", "Question", "must differ"),
        ("socrates", "feynman", "   ", "question is required"),
        ("socrates", "feynman", "x" * 2_001, "at most 2000"),
    ],
)
def test_user_created_invocation_validates_current_members_and_question(
    group_runtime,
    requester: str,
    target: str,
    question: str,
    message: str,
) -> None:
    manager, _partners, group = group_runtime

    with pytest.raises(ValueError, match=message):
        manager.create_invocation(
            group.group_id,
            session_key="direct-invocation",
            requester_partner_id=requester,
            target_partner_id=target,
            question=question,
        )


def test_user_created_invocation_is_pending_without_a_parent_turn(group_runtime) -> None:
    manager, _partners, group = group_runtime

    invocation = manager.create_invocation(
        group.group_id,
        session_key="direct-invocation",
        requester_partner_id="socrates",
        target_partner_id="feynman",
        question="  Which boundary case should we test?  ",
    )

    assert invocation.status == "pending"
    assert invocation.parent_turn_id == ""
    assert invocation.requester_partner_name == "Socrates"
    assert invocation.target_partner_name == "Feynman"
    assert invocation.question == "Which boundary case should we test?"
    rejected = manager.reject_invocation(
        group.group_id,
        invocation.invocation_id,
        session_key="direct-invocation",
    )
    assert rejected.status == "rejected"


@pytest.mark.asyncio
async def test_user_created_invocation_uses_existing_approval_flow(
    group_runtime,
    monkeypatch,
) -> None:
    manager, partners, group = group_runtime

    async def send_group_message(partner_id, content, **kwargs):
        assert partner_id == "feynman"
        assert "Socrates asks you directly" in content
        assert kwargs["allow_invoke_other"] is False
        return "The boundary case is zero."

    monkeypatch.setattr(partners, "send_group_message", send_group_message)
    invocation = manager.create_invocation(
        group.group_id,
        session_key="direct-approval",
        requester_partner_id="socrates",
        target_partner_id="feynman",
        question="Which boundary case matters?",
    )

    reply = await manager.approve_invocation(
        group.group_id,
        invocation.invocation_id,
        session_key="direct-approval",
    )

    assert reply.kind == "invocation_reply"
    assert reply.content == "The boundary case is zero."
    assert manager.invocations(group.group_id, "direct-approval")[0]["status"] == ("completed")


def test_transcript_render_has_an_absolute_budget(tmp_path: Path) -> None:
    transcript = GroupTranscriptStore(tmp_path)
    transcript.append(
        GroupMessage(
            event_id=uuid4().hex,
            turn_id=uuid4().hex,
            session_key="budget",
            role="partner",
            content="newest-marker-" + ("x" * (PUBLIC_TRANSCRIPT_MAX_CHARS * 2)),
            author_id="socrates",
            author_name="Socrates",
            created_at=utc_now(),
        )
    )

    rendered = transcript.render("budget")

    assert len(rendered) == PUBLIC_TRANSCRIPT_MAX_CHARS
    assert rendered.startswith("Socrates: newest-marker-")


async def _append(items: list[dict], frame: dict) -> None:
    items.append(frame)


@pytest.mark.asyncio
async def test_debate_with_one_target_skips_the_clash_round(group_runtime, monkeypatch) -> None:
    """Addressing a single Partner must not make it argue against itself."""
    manager, partners, group = group_runtime
    manager.update_group(group.group_id, {"discussion_mode": "debate"})
    calls: list[str] = []

    async def send_group_message(partner_id, content, **kwargs):
        calls.append(content)
        return f"{partner_id} says"

    monkeypatch.setattr(partners, "send_group_message", send_group_message)
    result = await manager.send_message(
        group.group_id,
        content="@socrates what do you think?",
        session_key="debate-solo",
        mentions=["socrates"],
    )

    assert [reply.author_id for reply in result.replies] == ["socrates"]
    assert [reply.kind for reply in result.replies] == ["message"]
    assert len(calls) == 1
    assert "clash round" not in calls[0]


@pytest.mark.asyncio
async def test_debate_clash_round_cannot_propose_peer_questions(group_runtime, monkeypatch) -> None:
    """The clash round already answers peers; a proposal would duplicate it."""
    manager, partners, group = group_runtime
    manager.update_group(group.group_id, {"discussion_mode": "debate"})
    seen: list[tuple[str, bool]] = []

    async def send_group_message(partner_id, content, **kwargs):
        # The clash instruction also mentions "other opening statements", so
        # the phase is keyed off the opening instruction's exact wording.
        phase = "opening" if "debate's opening statement" in content else "clash"
        seen.append((phase, kwargs["allow_invoke_other"]))
        return f"{partner_id} {phase}"

    monkeypatch.setattr(partners, "send_group_message", send_group_message)
    await manager.send_message(
        group.group_id,
        content="Correct errors first or encourage first?",
        session_key="debate-invoke",
    )

    assert {flag for phase, flag in seen if phase == "opening"} == {True}
    assert {flag for phase, flag in seen if phase == "clash"} == {False}
