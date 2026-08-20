"""``load_entry_point_group`` is the one place third-party plugin code is imported.

Its whole job is containment: a plugin that raises on import, or that the
coercer rejects, must not stop the rest of the group from loading.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import deeptutor.core.entry_points as ep_module
from deeptutor.core.entry_points import load_entry_point_group


def _ep(name: str, load):
    return SimpleNamespace(name=name, load=load)


def _keep(_name: str, loaded: object) -> object | None:
    return loaded


def _stub(monkeypatch: pytest.MonkeyPatch, entries: list[object]) -> None:
    def _entry_points(*, group: str):
        assert group == "demo.group"
        return entries

    monkeypatch.setattr(ep_module, "entry_points", _entry_points)


def test_loads_every_healthy_entry_point(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub(monkeypatch, [_ep("a", lambda: "one"), _ep("b", lambda: "two")])
    assert load_entry_point_group("demo.group", _keep) == ["one", "two"]


def test_a_raising_entry_point_does_not_stop_the_others(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def _boom():
        raise RuntimeError("import blew up")

    _stub(monkeypatch, [_ep("broken", _boom), _ep("healthy", lambda: "kept")])

    with caplog.at_level("WARNING"):
        assert load_entry_point_group("demo.group", _keep) == ["kept"]

    assert "broken" in caplog.text


def test_a_raising_coercer_is_contained_too(monkeypatch: pytest.MonkeyPatch) -> None:
    def _picky(name: str, loaded: object) -> object | None:
        if name == "bad":
            raise ValueError("cannot use this")
        return loaded

    _stub(monkeypatch, [_ep("bad", lambda: "x"), _ep("good", lambda: "y")])
    assert load_entry_point_group("demo.group", _picky) == ["y"]


def test_a_rejected_entry_point_is_dropped_silently_here(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ``None`` is the coercer's own verdict, so it owns the explanation."""
    _stub(monkeypatch, [_ep("a", lambda: "one"), _ep("b", lambda: "two")])
    kept = load_entry_point_group(
        "demo.group", lambda name, loaded: None if name == "a" else loaded
    )
    assert kept == ["two"]


def test_an_unreadable_group_yields_nothing(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def _explode(*, group: str):
        raise OSError("metadata unreadable")

    monkeypatch.setattr(ep_module, "entry_points", _explode)

    with caplog.at_level("WARNING"):
        assert load_entry_point_group("demo.group", _keep) == []

    assert "demo.group" in caplog.text


def test_no_entry_points_is_not_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub(monkeypatch, [])
    assert load_entry_point_group("demo.group", _keep) == []
