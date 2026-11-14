"""``mastery_quiz.options`` sent as a JSON-encoded string is read as the array.

HKUDS/DeepTutor#2687: the schema declares ``options`` as an array, but models
intermittently serialise it into a string (``'[{"label": "A", …}]'``). The
tool rejected that as "not an array", and a model that repeated the shape on
every retry ended the turn as ``capability_incomplete``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deeptutor.capabilities.mastery.tools import MasteryQuizTool, _read_choice_options
from deeptutor.learning.models import (
    KnowledgePoint,
    KnowledgeType,
    LearningModule,
    LearningProgress,
)
from deeptutor.learning.storage import LearningStore

_OBJECTS = [
    {"label": "A", "body": "4.0 2 333"},
    {"label": "B", "body": "4 2 333"},
    {"label": "C", "body": "4.0 2.0 333"},
]


def test_json_string_of_option_objects_reads_like_the_array() -> None:
    assert _read_choice_options(json.dumps(_OBJECTS)) == _read_choice_options(_OBJECTS)


def test_json_string_of_plain_strings_reads_like_the_array() -> None:
    texts = ["4.0 2 333", "4 2 333", "4.0 2.0 333"]

    assert _read_choice_options(f"  {json.dumps(texts)}\n") == _read_choice_options(texts)


@pytest.mark.parametrize("raw", ["A: red, B: blue", "[not json", '"just a string"', ""])
def test_a_string_that_is_not_an_encoded_array_says_to_send_a_real_array(raw: str) -> None:
    with pytest.raises(ValueError, match="must be a JSON array, not a string"):
        _read_choice_options(raw)


def _use_store_root(monkeypatch, root: Path) -> None:
    def _init(self, root_arg=None):
        self._root = root / "learning"
        self._root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(LearningStore, "__init__", _init)


@pytest.mark.asyncio
async def test_registration_accepts_options_sent_as_a_json_string(tmp_path, monkeypatch) -> None:
    _use_store_root(monkeypatch, tmp_path)
    LearningStore().save(
        LearningProgress(
            book_id="path-1",
            modules=[
                LearningModule(
                    id="m1",
                    name="Numbers",
                    order=0,
                    knowledge_points=[
                        KnowledgePoint(
                            id="path-1-kp1",
                            name="literals",
                            type=KnowledgeType.CONCEPT,
                            module_id="m1",
                        )
                    ],
                )
            ],
        )
    )

    result = await MasteryQuizTool().execute(
        _mastery_path_id="path-1",
        knowledge_point_id="path-1-kp1",
        question="Which line prints the float, the int and the string?",
        question_type="choice",
        options=json.dumps(_OBJECTS),
        expected_answer="A",
        explanation="Only A keeps the float literal.",
    )

    assert result.success is True, result.content
    pending = LearningStore().load("path-1").pending_question
    assert pending is not None
    assert sorted(option.body for option in pending.options) == sorted(
        option["body"] for option in _OBJECTS
    )
    assert pending.choice_map[pending.expected_answer] == "4.0 2 333"
