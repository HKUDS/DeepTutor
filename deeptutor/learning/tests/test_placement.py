"""Session placement: one outline per path, one study or review per point."""

from __future__ import annotations

import json

import pytest

from deeptutor.capabilities.mastery.mode import STUDY
from deeptutor.learning.placement import (
    commit_outline_addition,
    lecture_coverage,
    lecture_diff,
    lecture_status,
    relocate_new_points,
    resolve_placed_session,
)
from deeptutor.learning.storage import LearningStore
from deeptutor.learning.topic_generation import _MAX_OBJECTIVES_PER_MODULE
from deeptutor.services.session.sqlite_store import SQLiteSessionStore
from deeptutor.tools.mastery_tool import MasteryBuildTool, MasteryReviseTool


@pytest.fixture
def path_id(tmp_path, monkeypatch):
    def _init(self, root_arg=None):
        from pathlib import Path

        self._root = Path(tmp_path) / "learning"
        self._root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(LearningStore, "__init__", _init)
    chat = SQLiteSessionStore(db_path=tmp_path / "chat.sqlite3")
    monkeypatch.setattr("deeptutor.services.session.get_session_store", lambda: chat)
    return "placed_path"


async def _build(path_id: str) -> None:
    result = await MasteryBuildTool().execute(
        _mastery_path_id=path_id,
        path_name="放置",
        modules=[
            {
                "name": "模块",
                "objective": "能说出这一节在讲什么",
                "knowledge_points": [
                    {"name": "概念甲", "type": "concept"},
                    {"name": "概念乙", "type": "concept"},
                ],
            }
        ],
    )
    assert result.success, result.content


@pytest.mark.asyncio
async def test_outline_is_one_session_and_study_is_per_point(path_id):
    await _build(path_id)
    store = LearningStore()
    progress = store.load(path_id)
    assert progress is not None
    first, second = (point.id for point in progress.modules[0].knowledge_points)

    outline = await resolve_placed_session(path_id, "outline", store=store)
    again = await resolve_placed_session(path_id, "outline", "ignored", store=store)
    assert outline["created"] is True
    assert again["session_id"] == outline["session_id"]
    assert again["created"] is False
    assert store.find_placed_session(path_id, "outline") == outline["session_id"]

    study_a = await resolve_placed_session(path_id, "study", first, store=store)
    study_b = await resolve_placed_session(path_id, "study", second, store=store)
    review_a = await resolve_placed_session(path_id, "review", first, store=store)
    assert len({outline["session_id"], study_a["session_id"], study_b["session_id"], review_a["session_id"]}) == 4
    assert (await resolve_placed_session(path_id, "study", first, store=store))["session_id"] == study_a["session_id"]


@pytest.mark.asyncio
async def test_a_study_preview_is_saved_only_when_the_learner_confirms(path_id):
    await _build(path_id)
    store = LearningStore()
    progress = store.load(path_id)
    assert progress is not None
    point_id = progress.modules[0].knowledge_points[0].id
    module_id = progress.modules[0].id
    study = await resolve_placed_session(path_id, "study", point_id, store=store)
    preview = await MasteryReviseTool().execute(
        _mastery_path_id=path_id,
        _mastery_session_mode=STUDY,
        _session_id=study["session_id"],
        action="preview",
        module_id=module_id,
        add=[{"name": "新的知识点", "type": "concept"}],
    )
    assert preview.success, preview.content
    payload = json.loads(preview.content)
    assert payload["status"] == "preview_only_not_saved"
    refused = await MasteryReviseTool().execute(
        _mastery_path_id=path_id,
        _mastery_session_mode=STUDY,
        _session_id=study["session_id"],
        module_id=module_id,
        add=[{"name": "不该直接写入", "type": "concept"}],
    )
    assert refused.success is False

    receipt = await commit_outline_addition(
        path_id,
        preview_id=int(payload["preview_id"]),
        session_id=study["session_id"],
        module_id=module_id,
        store=store,
    )
    assert receipt["status"] == "committed"
    saved = store.load(path_id)
    assert saved is not None
    names = [point.name for point in saved.modules[0].knowledge_points]
    assert "新的知识点" in names
    outline_id = store.find_placed_session(path_id, "outline")
    from deeptutor.services import session as session_services

    bubbles = await session_services.get_session_store().list_bubble_texts(outline_id)
    assert any("新的知识点" in row["content"] for row in bubbles)


def test_new_points_move_into_the_confirmed_module_until_the_cap():
    current = {f"kp{i}" for i in range(2)}
    modules = [
        {
            "id": "m1",
            "knowledge_points": [{"id": "kp0"}, {"id": "fresh", "name": "新的"}],
        },
        {"id": "m2", "knowledge_points": [{"id": "kp1"}]},
    ]
    moved = relocate_new_points(modules, current, "m2")
    assert [point["id"] for point in moved[0]["knowledge_points"]] == ["kp0"]
    assert [point["id"] for point in moved[1]["knowledge_points"]] == ["kp1", "fresh"]

    full = {
        "id": "m2",
        "knowledge_points": [{"id": f"old{i}"} for i in range(_MAX_OBJECTIVES_PER_MODULE)],
    }
    with pytest.raises(ValueError, match="30"):
        relocate_new_points(
            [{"id": "m1", "knowledge_points": [{"id": "fresh"}]}, full],
            {f"old{i}" for i in range(_MAX_OBJECTIVES_PER_MODULE)},
            "m2",
        )


def test_a_lecture_is_stale_once_study_moves_past_its_watermark():
    store = LearningStore.__new__(LearningStore)
    store.get_lecture = lambda *_args, **_kwargs: {  # type: ignore[method-assign]
        "body": "已有讲义",
        "covered_message_id": 4,
        "revision": 3,
        "confirmed_at": 1,
        "source": "learner_confirmed",
        "updated_at": 1,
    }
    store.get_lecture_draft = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
    status = lecture_status(
        store,
        "path",
        "kp",
        [{"id": 4, "role": "assistant", "content": "old"}, {"id": 9, "role": "user", "content": "new"}],
    )
    assert status["stale"] is True
    assert status["has_study"] is True
    assert status["latest_message_id"] == 9
    assert status["status"] == "confirmed"
    assert status["revision"] == 3
    assert status["draft"] is None


def test_a_draft_only_point_still_renders_something_to_read():
    """Review must not open empty when study rolled a lecture nobody confirmed."""
    store = LearningStore.__new__(LearningStore)
    store.get_lecture = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
    store.get_lecture_draft = lambda *_args, **_kwargs: {  # type: ignore[method-assign]
        "session_id": "s1",
        "body": "草稿讲义",
        "diff": [],
        "base_revision": 0,
        "covered_message_id": 9,
        "origin": "study_roll",
        "updated_at": 1,
    }
    status = lecture_status(store, "path", "kp", [{"id": 9, "role": "assistant", "content": "x"}])
    assert status["status"] == "draft_only"
    assert status["body"] == "草稿讲义"
    assert status["confirmed_body"] == ""
    assert status["draft"]["body"] == "草稿讲义"
    assert status["stale_from_study"] is False


@pytest.mark.asyncio
async def test_coverage_names_what_the_lecture_leaves_out(path_id):
    """A question and a check answer absent from the body are candidate gaps."""
    await _build(path_id)
    store = LearningStore()
    progress = store.load(path_id)
    assert progress is not None
    first = progress.modules[0].knowledge_points[0].id
    bubbles = [
        {"id": 1, "role": "assistant", "content": "讲了概念甲。"},
        {"id": 2, "role": "user", "content": "概念甲是什么？"},
        {"id": 3, "role": "user", "content": "它和反向传播的链式法则有什么关系？"},
    ]
    body = "# 概念甲\n\n这里只讲了概念甲本身。"
    report = lecture_coverage(
        store,
        path_id,
        first,
        bubbles,
        body,
        checks=[{"question": "循环怎么停？", "correct_answer": "最大步数限制"}],
    )
    missing_text = [item["text"] for item in report["missing"]]
    assert any("反向传播" in text for text in missing_text)
    assert any(item["kind"] == "check" for item in report["missing"])
    # A question the body already answers must not be reported.
    assert not any("概念甲是什么" in text for text in missing_text)
    assert report["count"] == len(report["missing"])


def test_lecture_diff_names_the_sections_it_changes():
    changes = lecture_diff("# 一\nA\n\n# 二\nB", "# 一\nA changed\n\n# 三\nC")
    by_op = {change["heading"]: change["op"] for change in changes}
    assert by_op == {"一": "replaced", "三": "added", "二": "removed"}


async def _study_turn(path_id: str, point_id: str, store: LearningStore, text: str) -> str:
    """Place the point's study session and give it one assistant bubble."""
    study = await resolve_placed_session(path_id, "study", point_id, store=store)
    from deeptutor.services import session as session_services

    await session_services.get_session_store().add_message(
        study["session_id"], "assistant", text
    )
    return study["session_id"]


@pytest.mark.asyncio
async def test_a_rolled_draft_is_unconfirmed_until_committed(path_id, monkeypatch):
    """Study leaves a draft; only an explicit commit makes it the lecture."""
    await _build(path_id)
    store = LearningStore()
    progress = store.load(path_id)
    assert progress is not None
    point_id = progress.modules[0].knowledge_points[0].id
    await _study_turn(path_id, point_id, store, "这一节讲了概念甲：它指的是……")

    async def fake_complete(*_args, **_kwargs):
        return "# 概念甲\n\n它是这一节的核心概念。"

    monkeypatch.setattr("deeptutor.services.llm.factory.complete", fake_complete)
    from deeptutor.learning.placement import commit_lecture_draft, write_lecture_draft

    draft = await write_lecture_draft(path_id, point_id, store=store)
    assert draft["status"] == "draft_only"
    assert draft["body"].startswith("# 概念甲")
    assert draft["confirmed_body"] == ""
    assert store.get_lecture(path_id, point_id) is None

    committed = commit_lecture_draft(store, path_id, point_id)
    assert committed["revision"] == 1
    assert store.get_lecture_draft(path_id, point_id) is None
    settled = store.get_lecture(path_id, point_id) or {}
    assert settled["body"].startswith("# 概念甲")
    assert settled["source"] == "learner_confirmed"


@pytest.mark.asyncio
async def test_rolling_a_draft_twice_merges_instead_of_rewriting(path_id, monkeypatch):
    """The draft is an input, so hand edits inside it survive the next roll."""
    await _build(path_id)
    store = LearningStore()
    progress = store.load(path_id)
    assert progress is not None
    point_id = progress.modules[0].knowledge_points[0].id
    session_id = await _study_turn(path_id, point_id, store, "讲了概念甲。")

    written: list[str] = []

    async def fake_complete(instruction, **_kwargs):
        written.append(str(instruction))
        return "# 概念甲\n\n第一版。"

    monkeypatch.setattr("deeptutor.services.llm.factory.complete", fake_complete)
    from deeptutor.learning.placement import write_lecture_draft

    await write_lecture_draft(path_id, point_id, store=store)
    from deeptutor.services import session as session_services

    await session_services.get_session_store().add_message(
        session_id, "assistant", "又补了一句关于概念甲的例子。"
    )
    second = await write_lecture_draft(path_id, point_id, store=store)
    # The second call read the first draft as its starting point rather than
    # composing from the whole transcript again.
    assert "--- CURRENT LECTURE ---" in written[-1]
    assert second["draft"]["body"] == "# 概念甲\n\n第一版。"


@pytest.mark.asyncio
async def test_a_lecture_is_written_from_the_whole_exchange_and_the_path(path_id, monkeypatch):
    """The learner's questions and neighbouring points are material, not noise."""
    await _build(path_id)
    store = LearningStore()
    progress = store.load(path_id)
    assert progress is not None
    first = progress.modules[0].knowledge_points[0].id
    session_id = await _study_turn(path_id, first, store, "概念甲指的是……")
    from deeptutor.services import session as session_services

    session_store = session_services.get_session_store()
    await session_store.add_message(session_id, "user", "它和概念乙有什么区别？")

    async def fake_list_notebook_entries(**_kwargs):
        return {
            "items": [
                {
                    "question": "Agent 循环的终止条件有哪几类？",
                    "correct_answer": "最大步数、任务完成、外部中断。",
                    "explanation": "三者缺一不可。",
                    "options": {},
                }
            ],
            "total": 1,
        }

    monkeypatch.setattr(session_store, "list_notebook_entries", fake_list_notebook_entries)

    written: list[str] = []

    async def fake_complete(instruction, **_kwargs):
        # The review pass is a second call; only the writer gets recorded here.
        if "You are writing" in str(_kwargs.get("system_prompt") or ""):
            written.append(str(instruction))
        return "# 概念甲\n\n它是这一节的核心概念。"

    monkeypatch.setattr("deeptutor.services.llm.factory.complete", fake_complete)
    from deeptutor.learning.placement import write_lecture_draft

    await write_lecture_draft(path_id, first, store=store)
    prompt = written[-1]
    assert "Learner: 它和概念乙有什么区别？" in prompt
    assert "--- PATH CONTEXT ---" in prompt
    assert "能说出这一节在讲什么" in prompt
    assert "概念乙" in prompt
    assert "CHECK QUESTIONS ALREADY ASKED" in prompt
    assert "Reference answer: 最大步数、任务完成、外部中断。" in prompt


@pytest.mark.asyncio
async def test_a_lecture_is_reviewed_and_revised_before_it_is_saved(path_id, monkeypatch):
    """Draft → Critique → Revise, bounded to one round."""
    await _build(path_id)
    store = LearningStore()
    progress = store.load(path_id)
    assert progress is not None
    first = progress.modules[0].knowledge_points[0].id
    await _study_turn(path_id, first, store, "讲了概念甲。")

    systems: list[str] = []

    async def fake_complete(instruction, *, system_prompt="", **_kwargs):
        systems.append(str(system_prompt))
        if "You review a lecture draft" in system_prompt:
            return (
                '{"verdict": "revise", "issues": '
                '[{"section": "概念甲", "problem": "缺少例子", "fix": "补一个例子"}]}'
            )
        if "reviewer read the lecture draft below" in instruction:
            return "# 概念甲\n\n补了例子的版本。"
        return "# 概念甲\n\n初稿。"

    monkeypatch.setattr("deeptutor.services.llm.factory.complete", fake_complete)
    from deeptutor.learning.placement import write_lecture_draft

    status = await write_lecture_draft(path_id, first, store=store)
    assert status["draft"]["body"] == "# 概念甲\n\n补了例子的版本。"
    assert any("You review a lecture draft" in system for system in systems)


@pytest.mark.asyncio
async def test_leaving_a_point_confirms_the_draft_and_can_be_undone(path_id, monkeypatch):
    """Walking forward is a decision; it has to be saved, and reversible."""
    await _build(path_id)
    store = LearningStore()
    progress = store.load(path_id)
    assert progress is not None
    first = progress.modules[0].knowledge_points[0].id
    await _study_turn(path_id, first, store, "讲了概念甲。")

    async def fake_complete(*_args, **_kwargs):
        return "# 概念甲\n\n留下。"

    monkeypatch.setattr("deeptutor.services.llm.factory.complete", fake_complete)
    from deeptutor.learning.placement import (
        auto_confirm_lecture,
        revert_lecture_confirmation,
        write_lecture_draft,
    )

    await write_lecture_draft(path_id, first, store=store)
    assert auto_confirm_lecture(path_id, first, store=store) is True
    saved = store.get_lecture(path_id, first) or {}
    assert saved["source"] == "implicit"
    # Nothing left to confirm, so leaving again is a no-op rather than a
    # second revision.
    assert auto_confirm_lecture(path_id, first, store=store) is False
    assert (store.get_lecture(path_id, first) or {})["revision"] == 1

    reverted = revert_lecture_confirmation(store, path_id, first)
    assert reverted["status"] == "reverted"
    assert store.get_lecture(path_id, first) is None
    # The text is not lost: it is back as a draft the learner can still apply.
    assert (store.get_lecture_draft(path_id, first) or {})["body"].startswith("# 概念甲")


@pytest.mark.asyncio
async def test_a_hand_edit_and_a_stale_confirm_cannot_both_win(path_id, monkeypatch):
    """Two writers on one lecture: the stale one is refused, not merged."""
    await _build(path_id)
    store = LearningStore()
    progress = store.load(path_id)
    assert progress is not None
    point_id = progress.modules[0].knowledge_points[0].id
    await _study_turn(path_id, point_id, store, "讲了概念甲。")

    async def fake_complete(*_args, **_kwargs):
        return "# 概念甲\n\n草稿。"

    monkeypatch.setattr("deeptutor.services.llm.factory.complete", fake_complete)
    from deeptutor.learning.placement import commit_lecture_draft, write_lecture_draft

    await write_lecture_draft(path_id, point_id, store=store)
    commit_lecture_draft(store, path_id, point_id)
    store.save_lecture(
        path_id, point_id, "# 概念甲\n\n学习者自己改的。", 0, source="learner_edit", expected_revision=1
    )
    # A card still holding revision 1 must not overwrite revision 2.
    from deeptutor.learning.storage import LearningConflictError

    with pytest.raises(LearningConflictError):
        store.save_lecture(
            path_id, point_id, "# 概念甲\n\n旧标签写回。", 0, source="learner_edit", expected_revision=1
        )
    assert (store.get_lecture(path_id, point_id) or {})["body"].endswith("学习者自己改的。")
