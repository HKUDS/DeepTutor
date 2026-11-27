"""Starter-suggestion settings: per-user, clamped, and never fatal."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deeptutor.services.settings import starter_settings


class _FakePathService:
    def __init__(self, root: Path) -> None:
        self._root = root

    def get_settings_file(self, name: str) -> Path:
        return self._root / f"{name}.json"


@pytest.fixture(autouse=True)
def scoped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(starter_settings, "get_path_service", lambda: _FakePathService(tmp_path))
    return tmp_path


def test_defaults_without_a_file() -> None:
    assert starter_settings.get_starter_settings() == {
        "version": 1,
        "trace_count": starter_settings.DEFAULT_TRACE_COUNT,
        "ask_hint_enabled": True,
    }


def test_round_trip(scoped: Path) -> None:
    saved = starter_settings.save_starter_settings({"trace_count": 42})

    assert saved["trace_count"] == 42
    assert starter_settings.get_starter_settings()["trace_count"] == 42
    assert json.loads((scoped / "starters.json").read_text(encoding="utf-8"))["trace_count"] == 42


@pytest.mark.parametrize(
    "given,expected",
    [
        (0, starter_settings.TRACE_COUNT_RANGE[0]),
        (10_000, starter_settings.TRACE_COUNT_RANGE[1]),
        ("nonsense", starter_settings.DEFAULT_TRACE_COUNT),
        (None, starter_settings.DEFAULT_TRACE_COUNT),
    ],
)
def test_values_are_clamped_not_rejected(given, expected) -> None:
    """The file layer clamps so a hand-edited file can never wedge the feature.

    The API rejects the same values loudly — see ``ChatStarterSettingsUpdate``
    — so a bad request is still an error rather than a silent adjustment.
    """
    assert starter_settings.save_starter_settings({"trace_count": given})["trace_count"] == expected


def test_a_corrupt_file_falls_back_to_defaults(scoped: Path) -> None:
    (scoped / "starters.json").write_text("{not json", encoding="utf-8")

    assert (
        starter_settings.get_starter_settings()["trace_count"]
        == starter_settings.DEFAULT_TRACE_COUNT
    )


def test_ask_hint_switch_round_trip(scoped: Path) -> None:
    saved = starter_settings.save_starter_settings({"trace_count": 20, "ask_hint_enabled": False})

    assert saved["ask_hint_enabled"] is False
    assert starter_settings.ask_hint_enabled() is False
    stored = json.loads((scoped / "starters.json").read_text(encoding="utf-8"))
    assert stored["ask_hint_enabled"] is False


def test_saving_without_the_switch_keeps_it() -> None:
    """A draft or client from before the switch must not turn the hint back on."""
    starter_settings.save_starter_settings({"trace_count": 20, "ask_hint_enabled": False})

    saved = starter_settings.save_starter_settings({"trace_count": 30})

    assert saved == {"version": 1, "trace_count": 30, "ask_hint_enabled": False}


@pytest.mark.parametrize("given", ["false", 0, None, "off"])
def test_only_a_real_boolean_turns_the_hint_off(scoped: Path, given) -> None:
    (scoped / "starters.json").write_text(
        json.dumps({"trace_count": 20, "ask_hint_enabled": given}), encoding="utf-8"
    )

    assert starter_settings.ask_hint_enabled() is True


def test_the_service_reads_the_setting(monkeypatch: pytest.MonkeyPatch, scoped: Path) -> None:
    """The knob has to actually reach the material collector."""
    from deeptutor.services import suggestions
    import deeptutor.services.path_service as path_service

    monkeypatch.setattr(path_service, "get_path_service", lambda: _FakePathService(scoped))
    starter_settings.save_starter_settings({"trace_count": 7})

    assert suggestions._trace_count() == 7
