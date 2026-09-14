"""Tests for reaching a mastery topic from an ordinary chat.

The navigation layer (:mod:`deeptutor.learning.navigation`) and the four
permanently-mounted tools (:mod:`deeptutor.tools.mastery_nav`) answer "what am
I studying, and take me back to it" without teaching anything. What matters
here is that they read the atlas faithfully, resolve a learner's fuzzy
reference ("lesson 1") to a real module, and refuse to produce a hand-off card
that would open a screen the learner was not promised.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deeptutor.learning import navigation
from deeptutor.learning.models import (
    KnowledgePoint,
    KnowledgeType,
    LearningModule,
    TopicMetadata,
)
from deeptutor.learning.service import LearningService
from deeptutor.learning.storage import LearningStore
from deeptutor.services.session.sqlite_store import SQLiteSessionStore
from deeptutor.tools.mastery_nav import (
    MasteryNewSessionTool,
    MasteryOpenSessionTool,
    MasterySessionsTool,
    MasteryTopicsTool,
)


def _store_init_factory(root: Path):
    def _init(self, root_arg=None):  # mirrors LearningStore.__init__
        self._root = Path(root) / "learning"
        self._root.mkdir(parents=True, exist_ok=True)

    return _init


@pytest.fixture
def store(tmp_path, monkeypatch) -> LearningStore:
    monkeypatch.setattr(LearningStore, "__init__", _store_init_factory(tmp_path))
    return LearningStore()


@pytest.fixture
def session_store(tmp_path, monkeypatch) -> SQLiteSessionStore:
    store = SQLiteSessionStore(db_path=tmp_path / "chat.db")
    monkeypatch.setattr("deeptutor.services.session.get_session_store", lambda: store)
    monkeypatch.setattr("deeptutor.services.session.get_sqlite_session_store", lambda: store)
    return store


def _modules() -> list[LearningModule]:
    return [
        LearningModule(
            id="m1",
            name="Descriptive statistics",
            order=1,
            knowledge_points=[
                KnowledgePoint(id="kp1", name="Mean", type=KnowledgeType.MEMORY, module_id="m1"),
                KnowledgePoint(
                    id="kp2", name="Variance", type=KnowledgeType.CONCEPT, module_id="m1"
                ),
            ],
        ),
        LearningModule(
            id="m2",
            name="Sampling distributions",
            order=2,
            knowledge_points=[
                KnowledgePoint(id="kp3", name="CLT", type=KnowledgeType.CONCEPT, module_id="m2"),
            ],
        ),
    ]


def _create_topic(path_id: str = "stats_101", name: str = "Intro Statistics") -> None:
    LearningService().create_topic(
        path_id,
        name=name,
        modules=_modules(),
        metadata=TopicMetadata(path_id=path_id, goal="Pass the stats midterm", emoji="📊"),
        sources=[],
    )


def _payload(result) -> dict:
    return json.loads(result.content)


# ── the atlas read ───────────────────────────────────────────────────────────


def test_topic_cards_report_the_gate_counts_and_a_lesson_outline(store):
    _create_topic()

    payload = navigation.topic_cards()

    assert payload["total_topics"] == 1
    card = payload["topics"][0]
    assert card["path_id"] == "stats_101"
    assert card["name"] == "Intro Statistics"
    assert card["emoji"] == "📊"
    assert (card["objectives"], card["mastered"]) == (3, 0)
    assert [module["name"] for module in card["modules"]] == [
        "Descriptive statistics",
        "Sampling distributions",
    ]
    # The outline is what a navigator needs; the objectives under each module
    # are two orders of magnitude more text for the same question.
    assert "knowledge_points" not in card["modules"][0]


def test_a_scratch_path_from_a_chat_is_not_a_destination(store):
    # An ad-hoc path keyed by session id has no topic metadata and no map.
    store.bind_session("session_42", "session_42", owns_path=True)

    assert navigation.topic_cards()["topics"] == []
    assert navigation.find_topic("session_42") is None


def test_query_matches_the_topic_name_its_goal_and_its_lessons(store):
    _create_topic()

    assert navigation.topic_cards(query="statistics")["topics"]
    assert navigation.topic_cards(query="midterm")["topics"]
    assert navigation.topic_cards(query="sampling")["topics"]
    assert navigation.topic_cards(query="organic chemistry")["topics"] == []


def test_a_traversal_shaped_id_is_a_miss_not_a_crash(store):
    assert navigation.find_topic("../../etc/passwd") is None


# ── resolving what the learner said ──────────────────────────────────────────


@pytest.mark.parametrize(
    "reference,expected",
    [
        ("m1", "m1"),
        ("Descriptive statistics", "m1"),
        ("descriptive", "m1"),
        ("1", "m1"),
        ("2", "m2"),
        ("sampling", "m2"),
        # The model relays the learner's phrasing, not a bare integer.
        ("lesson 1", "m1"),
        ("Module 2", "m2"),
        ("第一课", "m1"),
        ("第二讲", "m2"),
    ],
)
def test_a_lesson_resolves_by_id_name_fragment_or_number(store, reference, expected):
    _create_topic()
    topic = navigation.find_topic("stats_101")
    assert topic is not None

    module = navigation.resolve_module(topic, reference)

    assert module is not None and module["module_id"] == expected


def test_an_unknown_lesson_resolves_to_nothing(store):
    _create_topic()
    topic = navigation.find_topic("stats_101")
    assert topic is not None

    assert navigation.resolve_module(topic, "regression") is None
    assert navigation.resolve_module(topic, "9") is None
    assert navigation.resolve_module(topic, "") is None


# ── the mount gate ───────────────────────────────────────────────────────────


def test_the_gate_creates_no_store_for_a_learner_who_has_never_studied(tmp_path, monkeypatch):
    monkeypatch.setattr(
        LearningStore,
        "default_db_path",
        staticmethod(lambda: tmp_path / "learning" / "mastery" / "mastery.sqlite3"),
    )

    assert navigation.learner_has_topics() is False
    assert not (tmp_path / "learning").exists()


def test_the_gate_opens_once_a_topic_exists(store, monkeypatch):
    monkeypatch.setattr(LearningStore, "default_db_path", staticmethod(lambda: store.db_path))

    assert navigation.learner_has_topics() is False
    _create_topic()
    assert navigation.learner_has_topics() is True


# ── the tools ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mastery_topics_lists_topics_with_ids_the_other_tools_take(store):
    _create_topic()

    payload = _payload(await MasteryTopicsTool().execute())

    assert payload["topics"][0]["path_id"] == "stats_101"
    assert "instruction" in payload


@pytest.mark.asyncio
async def test_mastery_topics_says_so_when_there_is_nothing_to_navigate(store):
    payload = _payload(await MasteryTopicsTool().execute())

    assert payload["topics"] == []
    assert "no mastery topics" in payload["instruction"].lower()


@pytest.mark.asyncio
async def test_mastery_sessions_lists_the_conversations_on_one_topic(store, session_store):
    _create_topic()
    session = await session_store.create_session(title="Sampling questions")
    store.bind_session("stats_101", session["id"])

    payload = _payload(await MasterySessionsTool().execute(path_id="stats_101"))

    assert payload["path_name"] == "Intro Statistics"
    assert [row["title"] for row in payload["sessions"]] == ["Sampling questions"]
    assert payload["sessions"][0]["awaiting_answer"] is False


@pytest.mark.asyncio
async def test_mastery_sessions_rejects_a_topic_that_does_not_exist(store):
    result = await MasterySessionsTool().execute(path_id="nope")

    assert result.success is False
    assert "mastery_topics" in result.content


@pytest.mark.asyncio
async def test_open_session_produces_a_hand_off_with_the_lesson_named(store, session_store):
    _create_topic()
    session = await session_store.create_session(title="Sampling questions")
    store.bind_session("stats_101", session["id"])

    payload = _payload(
        await MasteryOpenSessionTool().execute(
            path_id="stats_101",
            session_id=session["id"],
            module="lesson 1",
            opening_message="Take me back through lesson 1",
            reason="You never revisited it",
        )
    )

    assert payload["kind"] == "open"
    assert payload["session_id"] == session["id"]
    assert payload["session_title"] == "Sampling questions"
    # "lesson 1" is the learner's phrasing; the card must carry the real name.
    assert payload["module_id"] == "m1"
    assert payload["module_name"] == "Descriptive statistics"
    assert payload["opening_message"] == "Take me back through lesson 1"
    assert payload["objectives"] == 3


@pytest.mark.asyncio
async def test_open_session_refuses_a_conversation_from_another_topic(store, session_store):
    _create_topic()
    _create_topic("ml_path", "Machine Learning")
    stray = await session_store.create_session(title="Elsewhere")
    store.bind_session("ml_path", stray["id"])

    result = await MasteryOpenSessionTool().execute(
        path_id="stats_101",
        session_id=stray["id"],
    )

    # Landing there would put the learner in front of a tutor that knows
    # nothing about what this chat just promised them.
    assert result.success is False
    assert "no conversation" in result.content


@pytest.mark.asyncio
async def test_open_session_requires_a_session_id(store):
    _create_topic()

    result = await MasteryOpenSessionTool().execute(path_id="stats_101")

    assert result.success is False
    assert "mastery_new_session" in result.content


@pytest.mark.asyncio
async def test_new_session_hands_off_without_touching_progress(store):
    _create_topic()
    before = LearningStore().load("stats_101")

    payload = _payload(
        await MasteryNewSessionTool().execute(
            path_id="stats_101",
            module="Sampling distributions",
            opening_message="Review sampling with me",
        )
    )

    assert payload["kind"] == "new"
    assert payload["session_id"] == ""
    assert payload["module_id"] == "m2"
    after = LearningStore().load("stats_101")
    assert after is not None and before is not None
    assert after.version == before.version
    assert after.mastery_levels == before.mastery_levels


@pytest.mark.asyncio
async def test_an_invented_lesson_is_refused_with_the_real_outline(store):
    _create_topic()

    result = await MasteryNewSessionTool().execute(path_id="stats_101", module="regression")

    # A card advertising a lesson the topic does not have is worse than no
    # card: the learner clicks it and the tutor teaches something else.
    assert result.success is False
    assert "Descriptive statistics" in result.content
    assert "Sampling distributions" in result.content
