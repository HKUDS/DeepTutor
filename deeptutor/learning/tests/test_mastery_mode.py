"""The mode decides what a mastery conversation may do — and can change.

Enforcement lives at call time rather than at mount time (see
``deeptutor.capabilities.mastery.mode``), so these drive the tools directly:
that is exactly where the guarantee now is.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deeptutor.capabilities.mastery.mode import (
    MODES,
    OUTLINE,
    REVIEW,
    STUDY,
    enforced_mode,
    normalize_mode,
    owning_modes,
    tool_is_allowed,
)
from deeptutor.capabilities.mastery.tools import MASTERY_TOOL_NAMES
from deeptutor.learning.storage import LearningStore
from deeptutor.tools.mastery_tool import (
    MasteryAssessTool,
    MasteryBuildTool,
    MasteryModeTool,
    MasteryQuizTool,
    MasteryReviseTool,
    MasteryStatusTool,
)


@pytest.fixture
def path_id(tmp_path, monkeypatch):
    def _init(self, root_arg=None):
        from pathlib import Path

        self._root = Path(tmp_path) / "learning"
        self._root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(LearningStore, "__init__", _init)
    return "test_path"


async def _build(path_id, mode=OUTLINE):
    return await MasteryBuildTool().execute(
        _mastery_path_id=path_id,
        _mastery_session_mode=mode,
        path_name="扩散模型",
        modules=[
            {
                "name": "前向过程",
                "objective": "说清楚噪声是怎么一步步加上去的",
                "knowledge_points": [
                    {"name": "加噪调度", "type": "concept"},
                    {"name": "重参数化技巧", "type": "concept"},
                ],
            }
        ],
    )


# ── the table itself ───────────────────────────────────────────────────────


def test_changing_the_map_belongs_to_outline_alone():
    for tool in ("mastery_build", "mastery_revise"):
        assert owning_modes(tool) == (OUTLINE,), tool
        assert tool_is_allowed(tool, OUTLINE)
        assert not tool_is_allowed(tool, STUDY)
        assert not tool_is_allowed(tool, REVIEW)


def test_examining_belongs_to_study_and_review():
    for tool in (
        "mastery_quiz",
        "mastery_grade",
        "mastery_assess",
        "mastery_skip_question",
    ):
        assert owning_modes(tool) == (STUDY, REVIEW), tool
        assert not tool_is_allowed(tool, OUTLINE)


def test_everything_else_is_shared_by_every_mode():
    """ "Where am I", "who is learning this", "read that", "change modes" are
    true regardless of what the sitting is for."""
    shared = {
        "mastery_status",
        "mastery_mode",
        "mastery_profile",
        "mastery_paths",
        "mastery_switch",
        "mastery_leave",
    }
    assert shared <= set(MASTERY_TOOL_NAMES)
    for tool in shared:
        for mode in MODES:
            assert tool_is_allowed(tool, mode), (tool, mode)


def test_a_conversation_that_never_recorded_a_mode_is_not_restricted():
    """The CLI, the SDK and every pre-modes conversation pass no mode. Reading
    that as a real mode would forbid things they have always been able to do."""
    assert enforced_mode(None) is None
    assert enforced_mode("") is None
    assert enforced_mode("something_new") is None
    for tool in MASTERY_TOOL_NAMES:
        assert tool_is_allowed(tool, None), tool
    # …while the mode shown and framed with still has to be *something*.
    assert normalize_mode(None) == STUDY


# ── enforcement, driven through the real tools ─────────────────────────────


@pytest.mark.asyncio
async def test_an_outline_mode_conversation_cannot_examine_the_learner(path_id):
    await _build(path_id)
    refused = await MasteryQuizTool().execute(
        _mastery_path_id=path_id,
        _mastery_session_mode=OUTLINE,
        knowledge_point_id=f"{path_id}_m0_kp0",
        question="加噪调度是什么？",
        expected_answer="A",
        question_type="short",
    )
    assert refused.success is False
    assert "mastery_mode" in refused.content


@pytest.mark.asyncio
async def test_a_study_mode_conversation_cannot_replace_the_agreed_outline(path_id):
    await _build(path_id)
    refused = await MasteryBuildTool().execute(
        _mastery_path_id=path_id,
        _mastery_session_mode=STUDY,
        modules=[{"name": "别的课", "knowledge_points": [{"name": "别的知识点"}]}],
    )
    assert refused.success is False
    assert "'outline'" in refused.content
    # …and the agreed outline is untouched.
    status = json.loads(
        (
            await MasteryStatusTool().execute(_mastery_path_id=path_id, _mastery_session_mode=STUDY)
        ).content
    )
    assert [m["name"] for m in status["map"]["modules"]] == ["前向过程"]
    assert status["mode"] == STUDY


@pytest.mark.asyncio
async def test_review_refuses_a_knowledge_point_that_is_not_mastered_yet(path_id):
    """What separates reviewing from studying, now that a due date no longer
    gates the mode: review re-tests proven work, it does not open new ground."""
    await _build(path_id)
    refused = await MasteryQuizTool().execute(
        _mastery_path_id=path_id,
        _mastery_session_mode=REVIEW,
        knowledge_point_id=f"{path_id}_m0_kp0",
        question="加噪调度是什么？",
        expected_answer="A",
        question_type="short",
    )
    assert refused.success is False
    assert "study" in refused.content


@pytest.mark.asyncio
async def test_review_may_re_examine_something_already_mastered_even_when_not_due(path_id):
    """A due date is a reminder, not a permission — asking to go back over
    something you have mastered is always allowed."""
    await _build(path_id)
    kp = f"{path_id}_m0_kp0"
    passed = await MasteryAssessTool().execute(
        _mastery_path_id=path_id,
        _mastery_session_mode=STUDY,
        knowledge_point_id=kp,
        passed=True,
        explanation="解释得很清楚。",
    )
    assert json.loads(passed.content)["mastered"] is True

    again = await MasteryAssessTool().execute(
        _mastery_path_id=path_id,
        _mastery_session_mode=REVIEW,
        knowledge_point_id=kp,
        passed=True,
        explanation="复习时又讲了一遍。",
    )
    assert again.success is True


# ── switching ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_switching_mode_rebinds_the_live_turn_and_returns_the_new_framing(path_id):
    await _build(path_id)
    bound: list[str] = []
    result = await MasteryModeTool().execute(
        _mastery_path_id=path_id,
        _mastery_session_mode=OUTLINE,
        _bind_active_mode=bound.append,
        mode=STUDY,
        reason="大纲定好了，开始学",
    )
    payload = json.loads(result.content)
    assert payload["status"] == "switched"
    assert payload["previous_mode"] == OUTLINE and payload["mode"] == STUDY
    assert bound == [STUDY]
    # The system prompt above still frames the mode the turn opened in, so the
    # new one has to travel down inside the result.
    assert payload["instructions"].strip()


@pytest.mark.asyncio
async def test_a_tool_refused_for_the_wrong_mode_works_after_switching(path_id):
    """The whole point of a mutable mode: one call unlocks the tool inside the
    same turn, instead of asking the learner to open another conversation."""
    await _build(path_id)
    kp = f"{path_id}_m0_kp0"
    args = dict(
        _mastery_path_id=path_id,
        knowledge_point_id=kp,
        question="加噪调度是什么？",
        expected_answer="A",
        question_type="short",
    )
    assert (await MasteryQuizTool().execute(_mastery_session_mode=OUTLINE, **args)).success is False

    bound: list[str] = []
    await MasteryModeTool().execute(
        _mastery_path_id=path_id,
        _mastery_session_mode=OUTLINE,
        _bind_active_mode=bound.append,
        mode=STUDY,
    )
    assert (
        await MasteryQuizTool().execute(_mastery_session_mode=bound[-1], **args)
    ).success is True


@pytest.mark.asyncio
async def test_studying_a_goal_with_no_outline_is_the_one_refused_switch(path_id):
    refused = await MasteryModeTool().execute(
        _mastery_path_id=path_id, _mastery_session_mode=OUTLINE, mode=STUDY
    )
    assert refused.success is False
    assert "no outline" in refused.content


@pytest.mark.asyncio
async def test_switching_to_review_is_never_refused(path_id):
    """A due date is a passive reminder; active review is always allowed."""
    await _build(path_id)
    result = await MasteryModeTool().execute(
        _mastery_path_id=path_id, _mastery_session_mode=STUDY, mode=REVIEW
    )
    assert result.success is True
    assert json.loads(result.content)["mode"] == REVIEW


@pytest.mark.asyncio
async def test_revising_is_reachable_from_a_lesson_by_switching(path_id):
    await _build(path_id)
    module_id = f"{path_id}_m0"
    assert (
        await MasteryReviseTool().execute(
            _mastery_path_id=path_id,
            _mastery_session_mode=STUDY,
            module_id=module_id,
            remove=[f"{path_id}_m0_kp1"],
        )
    ).success is False

    bound: list[str] = []
    await MasteryModeTool().execute(
        _mastery_path_id=path_id,
        _mastery_session_mode=STUDY,
        _bind_active_mode=bound.append,
        mode=OUTLINE,
    )
    revised = await MasteryReviseTool().execute(
        _mastery_path_id=path_id,
        _mastery_session_mode=bound[-1],
        module_id=module_id,
        remove=[f"{path_id}_m0_kp1"],
    )
    assert revised.success is True
    assert [kp["name"] for kp in json.loads(revised.content)["knowledge_points"]] == ["加噪调度"]


# ── standing inside a goal the learner just created ────────────────────────


async def _create_goal(path_id, *, goal: str, name: str = "中国近代史"):
    """A goal made the way the wizard makes one: named, with a stated goal,
    and deliberately without an outline."""
    from deeptutor.learning.models import TopicMetadata
    from deeptutor.learning.service import LearningService

    store = LearningStore()
    return LearningService(store).create_topic(
        path_id,
        name=name,
        modules=[],
        metadata=TopicMetadata(path_id=path_id, goal=goal, emoji="🧭"),
        sources=[],
    )


@pytest.mark.asyncio
async def test_status_names_the_goal_it_is_standing_in(path_id):
    """The tutor could not see the sentence the learner wrote when they created
    the goal — the map carries a name, and the goal lived only in the
    dashboard. A conversation inside a brand-new goal therefore read as a
    conversation standing nowhere."""
    await _create_goal(path_id, goal="我想学习中国近代史")

    status = json.loads(
        (
            await MasteryStatusTool().execute(
                _mastery_path_id=path_id, _mastery_session_mode=OUTLINE
            )
        ).content
    )
    assert status["status"] == "empty"
    assert status["path_id"] == path_id
    assert status["path_name"] == "中国近代史"
    assert status["goal"] == "我想学习中国近代史"


@pytest.mark.asyncio
async def test_a_freshly_created_goal_is_never_reported_as_belonging_nowhere(path_id):
    """The failure this guards, verbatim from a real session: the tutor read
    "no outline" as "this conversation is not on a path", listed the five goals
    the learner had built before, and asked which one they meant — while
    standing inside the one they had just created."""
    # Two other goals exist, which is what used to trigger the "pick one" path.
    await _build("other_a")
    await _build("other_b")
    await _create_goal(path_id, goal="我想学习中国近代史")

    message = json.loads(
        (
            await MasteryStatusTool().execute(
                _mastery_path_id=path_id, _mastery_session_mode=OUTLINE
            )
        ).content
    )["message"]
    assert "中国近代史" in message
    assert "我想学习中国近代史" in message
    assert "mastery_build" in message
    # …and none of the invitations that sent it wandering.
    assert "mastery_switch" not in message
    assert "which one they mean" not in message


@pytest.mark.asyncio
async def test_a_scratch_conversation_still_offers_the_goals_built_elsewhere(path_id):
    """The other half of the same fork must keep working: a bare chat that
    resolved to its own id is genuinely not on any goal (#909)."""
    await _build("other_a")
    await _build("other_b")

    message = json.loads(
        (await MasteryStatusTool().execute(_mastery_path_id="scratch_session")).content
    )["message"]
    assert "not on a built path" in message
    assert "mastery_switch" in message


@pytest.mark.asyncio
async def test_a_built_goal_reports_its_identity_too(path_id):
    """Not only the empty case: the tutor should know which goal it is teaching
    on every round, not just before there is an outline."""
    await _create_goal(path_id, goal="我想学习中国近代史")
    await _build(path_id)

    status = json.loads(
        (
            await MasteryStatusTool().execute(_mastery_path_id=path_id, _mastery_session_mode=STUDY)
        ).content
    )
    assert status["status"] == "active"
    assert status["goal"] == "我想学习中国近代史"
    assert status["path_id"] == path_id


# ── what the prompt has to keep saying ─────────────────────────────────────


def _pack(language: str) -> dict:
    import yaml

    prompts = Path(__file__).resolve().parents[2] / "capabilities" / "mastery" / "prompts"
    return yaml.safe_load((prompts / language / "mastery_loop.yaml").read_text(encoding="utf-8"))


def test_study_never_offers_to_do_the_reviewing_itself(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The sentence this guards taught the tutor that due reviews are study's
    to handle, so "I want to review" was answered by quizzing a due item
    without leaving study — the learner asked for a mode and got a workaround.
    """
    monkeypatch.chdir(tmp_path)
    for language in ("zh", "en"):
        study = _pack(language)["session"]["study"]
        assert "mastery_status" in study
        # It may say due reviews are visible; it may not say study does them.
        assert "surfaces due reviews itself" not in study
        assert "到期复习项它会自己告诉你" not in study
        assert "review" in study


def test_naming_an_activity_is_documented_as_a_mode_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    for language in ("zh", "en"):
        playbook = _pack(language)["playbook"]
        assert "mastery_mode" in playbook
        marker = "那就是一次模式请求" if language == "zh" else "that is a mode request"
        assert marker in playbook, language


def test_the_outline_metaphor_is_gone_from_learner_facing_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """'Map' was a metaphor the product does not use anywhere the learner can
    see; the word is 'outline'."""
    monkeypatch.chdir(tmp_path)
    for language in ("zh", "en"):
        pack = _pack(language)
        blob = "\n".join(
            [
                pack["general"],
                pack["playbook"],
                *pack["session"].values(),
                pack["loop"]["system"],
            ]
        )
        assert "地图" not in blob, language
        assert " map" not in blob, language
