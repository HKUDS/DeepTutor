"""Choice options are shuffled on registration so the correct answer moves.

HKUDS/DeepTutor#1691: models put the correct option first nearly always, and
the registration order is exactly what the card renders, so quiz after quiz
read A = correct. The shuffle lives in the tool layer, after validation and
echo stripping; these tests pin the label remapping, its determinism under a
fixed rng, and the persisted end-to-end contract the grader relies on.
"""

from __future__ import annotations

from pathlib import Path
import random

import pytest

from deeptutor.capabilities.mastery.tools import MasteryQuizTool, _shuffle_choice_options
from deeptutor.learning.models import (
    KnowledgePoint,
    KnowledgeType,
    LearningModule,
    LearningProgress,
)
from deeptutor.learning.storage import LearningStore


def _use_store_root(monkeypatch, root: Path) -> None:
    def _init(self, root_arg=None):
        self._root = root / "learning"
        self._root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(LearningStore, "__init__", _init)


def _options() -> list[dict[str, str]]:
    return [
        {"label": "A", "body": "right"},
        {"label": "B", "body": "wrong-1"},
        {"label": "C", "body": "wrong-2"},
        {"label": "D", "body": "wrong-3"},
    ]


def test_expected_follows_its_body_to_the_new_label() -> None:
    shuffled, expected = _shuffle_choice_options(_options(), "A", random.Random(7))

    assert sorted(option["body"] for option in shuffled) == sorted(
        option["body"] for option in _options()
    )
    assert [option["label"] for option in shuffled] == ["A", "B", "C", "D"]
    assert next(option for option in shuffled if option["label"] == expected)["body"] == "right"


def test_a_fixed_rng_is_deterministic() -> None:
    once = _shuffle_choice_options(_options(), "A", random.Random(11))
    twice = _shuffle_choice_options(_options(), "A", random.Random(11))

    assert once == twice


def test_the_correct_answer_does_not_stay_on_one_label() -> None:
    labels = {
        _shuffle_choice_options(_options(), "A", random.Random(seed))[1] for seed in range(40)
    }

    assert len(labels) >= 2


def test_fewer_than_two_options_is_returned_unchanged() -> None:
    options = [{"label": "A", "body": "only"}]

    assert _shuffle_choice_options(options, "A", random.Random(3)) == (options, "A")


def _built_path(path_id: str = "path-1") -> LearningProgress:
    return LearningProgress(
        book_id=path_id,
        modules=[
            LearningModule(
                id="m1",
                name="Algebra",
                order=0,
                knowledge_points=[
                    KnowledgePoint(
                        id=f"{path_id}-kp1",
                        name="slope",
                        type=KnowledgeType.CONCEPT,
                        module_id="m1",
                    )
                ],
            )
        ],
    )


@pytest.mark.asyncio
async def test_registration_shuffles_the_card_the_learner_sees(tmp_path, monkeypatch) -> None:
    """The persisted pair must stay consistent: expected points at its body.

    The grader compares the learner's picked label against ``expected_answer``
    on the persisted options, so the shuffle may never decouple them — even
    though the model registered the correct option as A.
    """
    _use_store_root(monkeypatch, tmp_path)
    real_random_class = random.Random
    monkeypatch.setattr(
        "deeptutor.capabilities.mastery.tools.random.Random",
        lambda *args, **kwargs: real_random_class(7),
    )
    LearningStore().save(_built_path())

    result = await MasteryQuizTool().execute(
        _mastery_path_id="path-1",
        knowledge_point_id="path-1-kp1",
        question="Which option is correct?",
        question_type="choice",
        options=[
            {"label": "A", "body": "correct body"},
            {"label": "B", "body": "distractor one"},
            {"label": "C", "body": "distractor two"},
        ],
        expected_answer="A",
        explanation="because.",
    )

    assert result.success is True, result.content
    pending = LearningStore().load("path-1").pending_question
    assert pending is not None
    assert pending.question_type == "choice"
    assert sorted(option.body for option in pending.options) == [
        "correct body",
        "distractor one",
        "distractor two",
    ]
    assert [option.label for option in pending.options] == ["A", "B", "C"]
    assert pending.choice_map[pending.expected_answer] == "correct body"
