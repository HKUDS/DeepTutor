"""Recall — "what happened lately", across surfaces, on stamps alone."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from deeptutor.services.memory import recall
from deeptutor.services.memory.snapshot.entity import EntityStamp


def _iso(days: float) -> str:
    """An ISO stamp *days* in the past."""
    return (datetime.now(tz=timezone.utc) - timedelta(days=days)).isoformat()


def _stub_stamps(monkeypatch: pytest.MonkeyPatch, by_surface: dict[str, list[EntityStamp]]) -> None:
    from deeptutor.services.memory.snapshot import adapters

    monkeypatch.setattr(adapters, "read_stamps", lambda surface: by_surface.get(surface, []))


def _stamp(label: str, ts: str, ident: str = "") -> EntityStamp:
    return EntityStamp(id=ident or label, label=label, fingerprint="fp", ts=ts)


# ── recent ───────────────────────────────────────────────────────────────


def test_recent_merges_surfaces_newest_first(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_stamps(
        monkeypatch,
        {
            "chat": [_stamp("Chain rule", _iso(2))],
            "quiz": [_stamp("What is an eigenvalue?", _iso(0.5))],
            "book": [_stamp("Calculus notes", _iso(4))],
        },
    )

    hits = recall.recent()

    assert [(h.surface, h.label) for h in hits] == [
        ("quiz", "What is an eigenvalue?"),
        ("chat", "Chain rule"),
        ("book", "Calculus notes"),
    ]
    assert hits[0].days_ago == 0
    assert hits[1].days_ago == 2


def test_recent_honours_the_lookback_window(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_stamps(
        monkeypatch,
        {
            "chat": [_stamp("Yesterday", _iso(1)), _stamp("Last month", _iso(30))],
        },
    )

    assert [h.label for h in recall.recent(days=7)] == ["Yesterday"]
    assert len(recall.recent(days=None)) == 2


def test_recent_drops_undated_items(monkeypatch: pytest.MonkeyPatch) -> None:
    """An item of unknown age must not be asserted into "the last seven days".

    This is what keeps knowledge bases out: their snapshot timestamp is the
    earliest index time, so a KB in daily use would still look ancient.
    """
    _stub_stamps(
        monkeypatch,
        {
            "chat": [_stamp("Dated", _iso(1))],
            "kb": [_stamp("Physics KB", "")],
        },
    )

    assert [h.label for h in recall.recent()] == ["Dated"]


def test_recent_keeps_only_the_newest_of_a_repeated_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_stamps(
        monkeypatch,
        {
            "chat": [
                _stamp("Chain rule", _iso(3), ident="s1"),
                _stamp("chain RULE", _iso(1), ident="s2"),
            ],
        },
    )

    hits = recall.recent()

    assert len(hits) == 1
    assert hits[0].days_ago == 1


def test_recent_same_label_on_different_surfaces_is_kept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_stamps(
        monkeypatch,
        {
            "chat": [_stamp("Eigenvalues", _iso(1))],
            "book": [_stamp("Eigenvalues", _iso(2))],
        },
    )

    assert {h.surface for h in recall.recent()} == {"chat", "book"}


def test_recent_respects_limit_and_surface_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_stamps(
        monkeypatch,
        {
            "chat": [_stamp(f"S{i}", _iso(i)) for i in range(5)],
            "quiz": [_stamp("Q1", _iso(0.1))],
        },
    )

    assert len(recall.recent(limit=2)) == 2
    assert {h.surface for h in recall.recent(surfaces=["chat"])} == {"chat"}
    # An unrecognised surface name falls back to all rather than to nothing.
    assert {h.surface for h in recall.recent(surfaces=["nope"])} == {"chat", "quiz"}


def test_recent_survives_one_broken_surface(monkeypatch: pytest.MonkeyPatch) -> None:
    from deeptutor.services.memory.snapshot import adapters

    def _read(surface: str) -> list[EntityStamp]:
        if surface == "chat":
            raise RuntimeError("db locked")
        return [_stamp("Calculus notes", _iso(1))] if surface == "book" else []

    monkeypatch.setattr(adapters, "read_stamps", _read)

    assert [h.label for h in recall.recent()] == ["Calculus notes"]


def test_recent_collapses_whitespace_and_bounds_labels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_stamps(
        monkeypatch,
        {"chat": [_stamp("a  ragged\n\ntitle", _iso(1)), _stamp("x" * 400, _iso(2))]},
    )

    labels = [h.label for h in recall.recent()]

    assert labels[0] == "a ragged title"
    assert len(labels[1]) == 200


# ── recent_queries ───────────────────────────────────────────────────────


class _FakePathService:
    def __init__(self, root: Path) -> None:
        self._root = root

    def get_memory_dir(self) -> Path:
        return self._root


@pytest.fixture
def memory_root(tmp_path: Path):
    from deeptutor.services.memory.paths import memory_path_service_override

    with memory_path_service_override(_FakePathService(tmp_path)):
        yield tmp_path


def _write_trace(root: Path, surface: str, events: list[dict]) -> None:
    directory = root / "trace" / surface
    directory.mkdir(parents=True, exist_ok=True)
    by_day: dict[str, list[str]] = {}
    for event in events:
        day = event["ts"][:10]
        by_day.setdefault(day, []).append(json.dumps(event, ensure_ascii=False))
    for day, lines in by_day.items():
        (directory / f"{day}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _query_event(query: str, ts: str) -> dict:
    return {
        "id": f"kb:{query}",
        "ts": ts,
        "surface": "kb",
        "kind": "query",
        "payload": {"query": query, "kb_name": "Physics", "answer_chars": 120},
        "session_id": None,
        "turn_id": None,
    }


def test_recent_queries_reads_the_learners_own_words(memory_root: Path) -> None:
    _write_trace(
        memory_root,
        "kb",
        [
            _query_event("what is an eigenvalue", _iso(1)),
            _query_event("how does backprop work", _iso(0.2)),
        ],
    )

    hits = recall.recent_queries()

    assert [h.label for h in hits] == ["how does backprop work", "what is an eigenvalue"]
    assert {h.surface for h in hits} == {"kb"}


def test_recent_queries_ignores_other_event_kinds(memory_root: Path) -> None:
    other = _query_event("indexed something", _iso(1))
    other["kind"] = "index"
    _write_trace(memory_root, "kb", [other, _query_event("real question", _iso(1))])

    assert [h.label for h in recall.recent_queries()] == ["real question"]


def test_recent_queries_dedupes_a_repeated_search(memory_root: Path) -> None:
    _write_trace(
        memory_root,
        "kb",
        [
            _query_event("eigenvalues", _iso(3)),
            _query_event("eigenvalues", _iso(1)),
        ],
    )

    hits = recall.recent_queries()

    assert len(hits) == 1
    assert hits[0].days_ago == 1


def test_recent_queries_is_empty_without_a_trace(memory_root: Path) -> None:
    assert recall.recent_queries() == []
