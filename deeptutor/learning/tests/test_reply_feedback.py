"""Reply likes: one row per liked tutor reply, removable, summarized for the tutor."""

from __future__ import annotations

import pytest

from deeptutor.learning.storage import LearningStore
from deeptutor.tools.mastery_tool import MasteryBuildTool


@pytest.fixture
def store(tmp_path, monkeypatch):
    def _init(self, root_arg=None):
        from pathlib import Path

        self._root = Path(tmp_path) / "learning"
        self._root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(LearningStore, "__init__", _init)
    return LearningStore()


async def _build(path_id: str) -> None:
    result = await MasteryBuildTool().execute(
        _mastery_path_id=path_id,
        path_name="点赞路径",
        modules=[
            {
                "name": "模块",
                "objective": "能说出这一节在讲什么",
                "knowledge_points": [{"name": "概念甲", "type": "concept"}],
            }
        ],
    )
    assert result.success, result.content


@pytest.mark.asyncio
async def test_like_then_unlike_round_trip(store):
    await _build("like_path")

    liked = store.set_reply_feedback(
        "like_path",
        42,
        liked=True,
        session_id="s1",
        knowledge_point_id="kp1",
        excerpt="a good explanation",
    )
    assert liked["count"] == 1
    assert liked["liked"] is True
    assert liked["message_id"] == 42
    assert store.liked_message_ids("like_path", "s1") == [42]
    assert store.liked_message_ids("like_path") == [42]

    cleared = store.set_reply_feedback("like_path", 42, liked=False)
    assert cleared["count"] == 0
    assert store.liked_message_ids("like_path") == []


@pytest.mark.asyncio
async def test_summary_counts_and_recent_excerpt(store):
    await _build("summary_path")
    store.set_reply_feedback(
        "summary_path",
        1,
        liked=True,
        knowledge_point_id="kp1",
        excerpt="first",
    )
    store.set_reply_feedback(
        "summary_path",
        2,
        liked=True,
        knowledge_point_id="kp2",
        excerpt="second",
    )

    summary = store.reply_feedback_summary("summary_path")
    assert summary["count"] == 2
    assert summary["per_knowledge_point"] == {"kp1": 1, "kp2": 1}
    assert summary["recent"][0]["excerpt"] == "second"
