from __future__ import annotations

from types import SimpleNamespace

from pydantic import ValidationError
import pytest

from deeptutor.reading.extensions import (
    ReadingAction,
    ReadingContext,
    ReadingExtensionManifest,
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


def test_core_has_no_builtin_extensions(monkeypatch):
    monkeypatch.setattr(
        "deeptutor.reading.extensions.load_entry_point_group", lambda *_args, **_kwargs: []
    )
    registry = ReadingExtensionRegistry()
    assert registry.all() == []


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


def test_duplicate_extension_does_not_replace_first():
    first = SimpleNamespace(
        manifest=ReadingExtensionManifest(
            id="quiz",
            version="1",
            name="First",
            actions=[ReadingAction(id="start", label="Test")],
            result_types=["quiz"],
        ),
        run_action=lambda *_: ReadingExtensionResult(type="quiz"),
    )
    duplicate = SimpleNamespace(
        manifest=ReadingExtensionManifest(
            id="quiz",
            version="1",
            name="Duplicate",
            actions=[ReadingAction(id="start", label="Test")],
            result_types=["quiz"],
        ),
        run_action=lambda *_: pytest.fail("duplicate should not win"),
    )
    registry = ReadingExtensionRegistry([first, duplicate])
    assert registry.get("quiz") is first


def test_result_schema_rejects_unsafe_or_unbounded_shapes():
    with pytest.raises(ValidationError):
        ReadingExtensionResult(type="browser_speech", payload={"text": ""})
    with pytest.raises(ValidationError):
        ReadingExtensionResult(
            type="quiz",
            payload={"questions": [{"prompt": "Question", "choices": ["one"]}]},
        )
    with pytest.raises(ValidationError):
        ReadingExtensionResult(type="card", payload={"body": "x" * 70_000})


def test_manifest_rejects_non_toolbar_triggers():
    with pytest.raises(ValidationError):
        ReadingAction(id="open", label="Open", trigger="javascript")  # type: ignore[arg-type]
