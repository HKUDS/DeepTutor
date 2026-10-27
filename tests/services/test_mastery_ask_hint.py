"""The composer hint follows the conversation's knowledge point."""

import pytest

from deeptutor.learning.models import KnowledgePoint, LearningModule, LearningProgress
from deeptutor.learning.service import LearningService
from deeptutor.learning.storage import LearningStore
from deeptutor.services import mastery_hints


class _Sessions:
    def __init__(self, point_id: str):
        self.point_id = point_id

    async def get_session(self, session_id: str):
        return {"preferences": {"mastery_knowledge_point_id": self.point_id}}

    async def get_session_with_messages(self, session_id: str):
        return {"messages": [{"role": "user", "content": "从直觉讲起"}]}


def _save(tmp_path) -> LearningStore:
    store = LearningStore(root=tmp_path)
    LearningService(store).save(
        LearningProgress(
            book_id="path",
            modules=[
                LearningModule(
                    id="m0",
                    name="Agent loop",
                    order=0,
                    knowledge_points=[
                        KnowledgePoint(
                            id="react",
                            name="ReAct, reflection, and planning",
                            module_id="m0",
                            type="concept",
                        )
                    ],
                ),
                LearningModule(
                    id="m2",
                    name="Memory",
                    order=2,
                    knowledge_points=[
                        KnowledgePoint(
                            id="memory",
                            name="Long-term memory and session state",
                            module_id="m2",
                            type="concept",
                        )
                    ],
                ),
            ],
        )
    )
    return store


@pytest.mark.asyncio
async def test_ask_hint_material_uses_the_placed_point_not_the_frontier(tmp_path, monkeypatch):
    _save(tmp_path)
    monkeypatch.setattr(
        "deeptutor.learning.storage.LearningStore",
        lambda root=None: LearningStore(root=tmp_path),
    )
    monkeypatch.setattr(
        "deeptutor.services.session.get_session_store",
        lambda: _Sessions("memory"),
    )
    material = await mastery_hints._collect("path", "session-memory")
    assert material.waypoint == "Long-term memory and session state"
    assert material.anchor.startswith("memory:")


@pytest.mark.asyncio
async def test_ask_hint_without_a_placement_stays_on_the_frontier(tmp_path, monkeypatch):
    _save(tmp_path)
    monkeypatch.setattr(
        "deeptutor.learning.storage.LearningStore",
        lambda root=None: LearningStore(root=tmp_path),
    )
    monkeypatch.setattr(
        "deeptutor.services.session.get_session_store",
        lambda: _Sessions(""),
    )
    material = await mastery_hints._collect("path", "session-open")
    assert material.waypoint == "ReAct, reflection, and planning"
    assert material.anchor.startswith("react:")
