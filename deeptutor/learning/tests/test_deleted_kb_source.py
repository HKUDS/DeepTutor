"""A mastery topic must stop mounting a knowledge base that was deleted.

Topic sources are an insert-only snapshot of what the learner chose, so the
stored ``available`` flag cannot notice a base deleted afterwards. Liveness is
derived when the topic is read: the topic payload, the topic-materials
manifest, and the teaching turn's mounted knowledge bases all have to drop a
reference that no longer resolves, without rewriting the stored row.
"""

from __future__ import annotations

import pytest

from deeptutor.agents.loop.pipeline import AgenticLoopPipeline
from deeptutor.api.routers.mastery_path import _topic_payload_from_snapshot
from deeptutor.capabilities.mastery.pipeline import MasteryLoopPipeline
from deeptutor.core.context import UnifiedContext
from deeptutor.learning.models import (
    LearningProgress,
    MasteryTopic,
    TopicMetadata,
    TopicSource,
    TopicSourceKind,
)
from deeptutor.learning.storage import LearningStore
from deeptutor.learning.topic_materials import build_topic_materials
from deeptutor.multi_user.knowledge_access import current_kb_manager
from deeptutor.multi_user.models import CurrentUser, UserScope
from deeptutor.multi_user.paths import get_account_path_service, user_context
from deeptutor.services.llm.config import (
    LLMConfig,
    reset_scoped_llm_config,
    set_scoped_llm_config,
)

KB_NAME = "handbook"
PATH_ID = "states_101"


@pytest.fixture
def account(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPTUTOR_WORKSPACE_ROOT", raising=False)
    user = CurrentUser("kb-source", "kb-source", "admin", UserScope("admin", "kb-source", tmp_path))
    with user_context(user):
        get_account_path_service().ensure_all_directories()
        yield


def _register_kb(name: str) -> None:
    manager = current_kb_manager()
    folder = manager.base_dir / name
    (folder / "raw").mkdir(parents=True)
    (folder / "raw" / "notes.md").write_text("Regression notes", encoding="utf-8")
    manager.config = manager._load_config()
    manager.config.setdefault("knowledge_bases", {})[name] = {"path": name, "status": "ready"}
    manager._save_config()


def _create_topic(
    *, delete_kb: bool, kind: TopicSourceKind = TopicSourceKind.KNOWLEDGE_BASE
) -> MasteryTopic:
    _register_kb(KB_NAME)
    store = LearningStore()
    store.save(LearningProgress(book_id=PATH_ID))
    if kind is TopicSourceKind.FILE:
        source = TopicSource(
            id="src-file",
            kind=kind,
            source_id="notes.md",
            label="Regression notes",
            metadata={"kb_name": KB_NAME},
        )
    else:
        source = TopicSource(id="src-kb", kind=kind, source_id=KB_NAME, label="Handbook")
    topic = store.put_topic(
        TopicMetadata(path_id=PATH_ID, goal="Understand regression"),
        [source],
    )
    if delete_kb:
        assert current_kb_manager().delete_knowledge_base(KB_NAME, confirm=True) is True
    return topic


def _topic_payload(topic: MasteryTopic) -> dict:
    progress = LearningStore().load(PATH_ID)
    return _topic_payload_from_snapshot(progress, topic, 0, None)


def test_topic_payload_reports_a_deleted_kb_source_as_unavailable(account):
    topic = _create_topic(delete_kb=True)

    assert _topic_payload(topic)["sources"][0]["available"] is False
    # The snapshot stays evidence of what the learner chose; liveness is only
    # derived per read and never written back.
    assert LearningStore().get_topic(PATH_ID).sources[0].available is True


def test_topic_materials_mark_a_deleted_kb_source_unavailable(account):
    topic = _create_topic(delete_kb=True)

    materials = build_topic_materials(topic.sources)

    assert len(materials.materials) == 1
    assert materials.materials[0].available is False
    assert "removed" in materials.materials[0].note


@pytest.mark.asyncio
async def test_mastery_turn_does_not_mount_a_deleted_kb(account, monkeypatch):
    _create_topic(delete_kb=True)
    mounted: list[list[str]] = []

    async def run(self, context, stream):
        mounted.append(list(context.knowledge_bases))
        return {}

    monkeypatch.setattr(AgenticLoopPipeline, "run", run)

    # This suite sits outside the shared test conftest, so it supplies the model
    # config the pipeline constructor reads. The turn never calls the model.
    token = set_scoped_llm_config(LLMConfig(model="test-model", api_key="sk-test"))
    try:
        await MasteryLoopPipeline().run(UnifiedContext(metadata={"mastery_path_id": PATH_ID}), None)
    finally:
        reset_scoped_llm_config(token)

    assert mounted == [[]]


def test_a_live_kb_source_stays_available(account):
    topic = _create_topic(delete_kb=False)

    assert _topic_payload(topic)["sources"][0]["available"] is True
    material = build_topic_materials(topic.sources).materials[0]
    assert material.available is True
    assert f"kb_name={KB_NAME!r}" in material.note


def test_a_file_source_follows_the_base_that_holds_it(account):
    """A hand-picked document is only searchable while its base still exists."""
    topic = _create_topic(delete_kb=False, kind=TopicSourceKind.FILE)

    assert _topic_payload(topic)["sources"][0]["available"] is True
    material = build_topic_materials(topic.sources).materials[0]
    assert material.available is True
    assert f"kb_name={KB_NAME!r}" in material.note

    assert current_kb_manager().delete_knowledge_base(KB_NAME, confirm=True) is True

    assert _topic_payload(topic)["sources"][0]["available"] is False
    material = build_topic_materials(topic.sources).materials[0]
    assert material.available is False
    assert "removed" in material.note
