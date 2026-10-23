"""Read aggregates and their projections from one committed database revision."""

from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Iterator

import pytest

from deeptutor.learning.models import LearningEvidence, LearningProgress, TopicMetadata
from deeptutor.learning.storage import LearningStore


@pytest.mark.parametrize("view", ["evidence", "atlas"])
def test_read_view_survives_interleaved_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, view: str
) -> None:
    """A real second connection commits between the reader's SELECT statements."""
    reader = LearningStore(root=tmp_path)
    writer = LearningStore(root=tmp_path)
    progress = LearningProgress(book_id="snapshot", name="before")
    reader.save(progress)
    reader.put_topic(TopicMetadata(path_id="snapshot", goal="before"), [])
    original_connect = reader._connect
    wrote = False

    def commit_between_queries(statement: str) -> None:
        nonlocal wrote
        boundary = (
            "SELECT evidence_json FROM mastery_learning_evidence"
            if view == "evidence"
            else "SELECT * FROM mastery_topic_meta WHERE status"
        )
        if wrote or boundary not in statement:
            return
        wrote = True
        with writer.transaction("snapshot") as tx:
            tx.progress.name = "after"
            tx.progress.learning_evidence.append(
                LearningEvidence(knowledge_point_id="kp1", result="correct")
            )
            tx.put_topic(TopicMetadata(path_id="snapshot", goal="after"), [])
            tx.touch()

    @contextmanager
    def interleaved_connect(*, initialize: bool = True) -> Iterator[sqlite3.Connection]:
        with original_connect(initialize=initialize) as conn:
            conn.set_trace_callback(commit_between_queries)
            yield conn

    monkeypatch.setattr(reader, "_connect", interleaved_connect)
    if view == "evidence":
        loaded, evidence, count = reader.load_with_learning_evidence("snapshot", "kp1")
        assert loaded is not None and loaded.name == "before"
        assert evidence == loaded.learning_evidence == []
        assert count == 0
    else:
        [(loaded, topic, _sessions, _interaction)] = reader.list_topic_snapshots()
        assert loaded.name == topic.metadata.goal == "before"
    assert wrote
    current = writer.load("snapshot")
    assert current is not None and current.name == "after"
    assert len(current.learning_evidence) == 1
