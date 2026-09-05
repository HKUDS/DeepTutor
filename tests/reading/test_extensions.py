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


def test_builtins_load_when_no_entry_points_are_installed(monkeypatch):
    monkeypatch.setattr(
        "deeptutor.reading.extensions.load_entry_point_group",
        lambda *_args, **_kwargs: [],
    )
    registry = ReadingExtensionRegistry()
    assert {row.manifest.id for row in registry.all()} == {
        "read_aloud",
        "vocabulary",
        "quiz",
        "guided_learning",
        "translation",
    }


def test_explicit_empty_registry_stays_empty():
    assert ReadingExtensionRegistry([]).all() == []


def test_third_party_extensions_load_but_cannot_replace_builtins(monkeypatch):
    third_party = _extension()
    impostor = _extension("read_aloud")

    def load(_group, coerce, **_kwargs):
        return [
            row
            for name, candidate in [("sample", third_party), ("read_aloud", impostor)]
            if (row := coerce(name, candidate)) is not None
        ]

    monkeypatch.setattr("deeptutor.reading.extensions.load_entry_point_group", load)
    registry = ReadingExtensionRegistry()
    assert registry.get("sample") is third_party
    assert registry.get("read_aloud") is not impostor


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
