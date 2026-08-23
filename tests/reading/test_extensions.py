from __future__ import annotations

from types import SimpleNamespace

import pytest

from deeptutor.reading.extensions import (
    ReadingContext,
    ReadingExtensionRegistry,
    ReadingExtensionResult,
)
from deeptutor.reading.learning import LearningLedger


def _context() -> ReadingContext:
    return ReadingContext(
        material_id="abc12345",
        locator=1,
        unit_text="The moon reflects sunlight. It travels around Earth.",
        visible_text="The moon reflects sunlight.",
    )


def test_builtins_are_schema_driven_and_hide_quiz_answers():
    registry = ReadingExtensionRegistry()
    assert {row.manifest.id for row in registry.all()} >= {
        "read_aloud",
        "guided_learn",
        "vocabulary",
        "translation",
        "quiz",
    }
    result = registry.get("quiz").run_action("start", _context())  # type: ignore[union-attr]
    assert isinstance(result, ReadingExtensionResult)
    assert result.type == "quiz"
    assert len(result.payload["questions"]) == 3


def test_learning_ledger_is_idempotent(tmp_path, monkeypatch):
    from deeptutor.reading import learning

    monkeypatch.setattr(
        learning,
        "get_current_user",
        lambda: SimpleNamespace(id="u-1"),
    )
    ledger = LearningLedger(tmp_path)
    interaction = {
        "interaction_id": "i-1",
        "extension": "quiz",
        "action": "start",
        "material_id": "abc12345",
        "locator": 2,
    }
    result = {"payload": {"score": 2, "total": 3, "completed": True}}
    first = ledger.record(interaction=interaction, submission={"answers": {}}, result=result)
    second = ledger.record(interaction=interaction, submission={"answers": {}}, result=result)
    assert first == second
    assert len(ledger.records()) == 1


def test_broken_extension_does_not_replace_builtin():
    duplicate = SimpleNamespace(
        manifest=SimpleNamespace(id="quiz"),
        run_action=lambda *_: pytest.fail("duplicate should not win"),
    )
    registry = ReadingExtensionRegistry([*ReadingExtensionRegistry().all(), duplicate])
    assert registry.get("quiz") is not duplicate
