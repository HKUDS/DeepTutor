"""Tests for the soft learning journal store (#740)."""

from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.services.learning_journal.store import LearningJournalStore
from deeptutor.services.path_service import PathService


@pytest.fixture()
def journal_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LearningJournalStore:
    service = PathService(workspace_root=tmp_path / "data")
    monkeypatch.setattr(
        "deeptutor.services.learning_journal.store.get_path_service",
        lambda: service,
    )
    return LearningJournalStore()


def test_empty_status_explains_how_to_start(journal_store: LearningJournalStore) -> None:
    text = journal_store.status_markdown()
    assert "No learning journal yet" in text
    assert "learning_update" in text


def test_mission_session_and_records_round_trip(journal_store: LearningJournalStore) -> None:
    mission = journal_store.set_mission(
        topic="Fourier transform",
        why="Need it for signals coursework",
        level="intermediate",
    )
    assert mission.accepted
    session = journal_store.note_session(
        summary="Covered continuous FT definition and duality.",
        next_focus="Discrete FT and sampling intuition",
    )
    assert session.accepted
    record = journal_store.add_record(
        title="Duality",
        insight="Time stretch ↔ frequency squeeze is the first intuition to keep.",
    )
    assert record.accepted
    assert record.record_id == "lr_0001"

    text = journal_store.status_markdown()
    assert "Fourier transform" in text
    assert "Discrete FT" in text
    assert "lr_0001" in text
    assert "Duality" in text

    path = journal_store.journal_path()
    assert path.exists()
    again = journal_store.load()
    assert again.mission.topic == "Fourier transform"
    assert len(again.records) == 1
    assert path.read_text(encoding="utf-8").count("Fourier") >= 1


def test_add_record_dedupes(journal_store: LearningJournalStore) -> None:
    first = journal_store.add_record(title="Nyquist", insight="Sample at >2B.")
    second = journal_store.add_record(title="Nyquist", insight="Sample at >2B.")
    assert first.accepted and second.accepted
    assert second.deduplicated
    assert second.record_id == first.record_id
    assert len(journal_store.load().records) == 1


def test_set_mission_requires_topic(journal_store: LearningJournalStore) -> None:
    result = journal_store.set_mission(topic="  ")
    assert not result.accepted


def test_injection_snapshot_carries_mission_and_handoff(
    journal_store: LearningJournalStore,
) -> None:
    journal_store.set_mission(
        topic="Fourier transform",
        why="Signals coursework",
        level="intermediate",
    )
    journal_store.note_session(
        summary="Covered continuous FT definition.",
        next_focus="Discrete FT and sampling intuition",
    )
    text = journal_store.injection_markdown()
    assert "Fourier transform" in text
    assert "Discrete FT and sampling intuition" in text


def test_injection_snapshot_leaves_records_out(journal_store: LearningJournalStore) -> None:
    journal_store.set_mission(topic="Fourier transform")
    journal_store.add_record(title="Duality", insight="Time stretch means frequency squeeze.")
    text = journal_store.injection_markdown()
    assert "Duality" not in text
    assert "Time stretch" not in text


def test_injection_snapshot_is_empty_for_a_new_learner(journal_store: LearningJournalStore) -> None:
    assert journal_store.injection_markdown() == ""


def test_injection_snapshot_skips_records_only_journal(
    journal_store: LearningJournalStore,
) -> None:
    journal_store.add_record(title="Nyquist", insight="Sample at more than 2B.")
    assert journal_store.injection_markdown() == ""
