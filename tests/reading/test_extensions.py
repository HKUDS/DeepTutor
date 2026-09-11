from __future__ import annotations

from types import SimpleNamespace

from pydantic import ValidationError
import pytest

from deeptutor.reading.extensions import (
    ReadingAction,
    ReadingExtensionManifest,
    ReadingExtensionRegistry,
    ReadingExtensionResult,
)


def _extension(identifier: str = "sample"):
    return SimpleNamespace(
        manifest=ReadingExtensionManifest(
            id=identifier,
            version="1.0.0",
            name="Sample",
            actions=[ReadingAction(id="open", label="Open")],
            result_types=["card"],
        ),
        run_action=lambda *_: ReadingExtensionResult(type="card"),
    )


def test_registry_is_empty_when_no_entry_points_are_installed(monkeypatch):
    monkeypatch.setattr(
        "deeptutor.reading.extensions.load_entry_point_group",
        lambda *_args, **_kwargs: [],
    )
    assert ReadingExtensionRegistry().all() == []


def test_duplicate_extension_does_not_replace_the_first():
    first = _extension()
    duplicate = _extension()
    registry = ReadingExtensionRegistry([first, duplicate])
    assert registry.get("sample") is first


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
