from __future__ import annotations

import json

from deeptutor.knowledge.manager import KnowledgeBaseManager
from deeptutor.knowledge.progress_tracker import ProgressStage, ProgressTracker


def test_progress_tracker_persists_snapshot_and_config(tmp_path) -> None:
    tracker = ProgressTracker("demo-kb", tmp_path)

    tracker.update(
        ProgressStage.PROCESSING_DOCUMENTS,
        "Embedding batches: 2/8 complete",
        current=2,
        total=8,
    )

    assert tracker.progress_file.exists()

    with open(tracker.progress_file, encoding="utf-8") as f:
        payload = json.load(f)

    assert payload["stage"] == "processing_documents"
    assert payload["progress_percent"] == 25
    assert payload["message"] == "Embedding batches: 2/8 complete"

    manager = KnowledgeBaseManager(base_dir=str(tmp_path))
    status = manager.get_kb_status("demo-kb")

    assert status is not None
    assert status["status"] == "processing"
    assert status["progress"]["message"] == "Embedding batches: 2/8 complete"


def test_progress_tracker_get_progress_falls_back_to_config(tmp_path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path))
    manager.update_kb_status(
        name="demo-kb",
        status="processing",
        progress={
            "stage": "processing_documents",
            "message": "Recovered from kb_config",
            "percent": 60,
            "current": 3,
            "total": 5,
        },
    )

    tracker = ProgressTracker("demo-kb", tmp_path)

    assert tracker.get_progress() == {
        "stage": "processing_documents",
        "message": "Recovered from kb_config",
        "percent": 60,
        "current": 3,
        "total": 5,
    }


def test_progress_tracker_persists_structured_failure_metadata(tmp_path) -> None:
    tracker = ProgressTracker("demo-kb", tmp_path)

    tracker.update(
        ProgressStage.ERROR,
        "GraphRAG model is incompatible",
        error="Choose a chat model that supports structured output.",
        error_code="graphrag_model_incompatible",
        retryable=False,
    )

    with open(tracker.progress_file, encoding="utf-8") as handle:
        payload = json.load(handle)

    assert payload["error_code"] == "graphrag_model_incompatible"
    assert payload["retryable"] is False

    status = KnowledgeBaseManager(base_dir=str(tmp_path)).get_kb_status("demo-kb")
    assert status is not None
    assert status["progress"]["error_code"] == "graphrag_model_incompatible"
    assert status["progress"]["retryable"] is False
