"""Tests for course connections and learning surface integration for Stanford CME 295."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from deeptutor.services.courses import get_course_service
from deeptutor.services.courses_state import build_course_state
from deeptutor.services.path_service import get_path_service


@pytest.mark.asyncio
async def test_cme295_course_resources_attached():
    """Verify that Stanford CME 295 has reading, mastery path, and notebook attached."""
    service = get_course_service()
    course = service.get("course_ad839270ec36")
    assert course is not None
    assert course.name == "Stanford CME 295: Transformers & LLMs"

    kinds = {res.kind for res in course.resources}
    assert "reading_workspace" in kinds
    assert "mastery_path" in kinds
    assert "notebook" in kinds


@pytest.mark.asyncio
async def test_cme295_course_state_aggregates_connected_surfaces():
    """Verify course state connects Mastery Path, Question Bank, Immersive Reading, and Notebook."""
    state = await build_course_state("course_ad839270ec36")
    assert state is not None

    # 1. Reading Workspaces
    assert len(state["reading"]["workspaces"]) >= 1
    reading_ws = next(
        ws for ws in state["reading"]["workspaces"]
        if ws["workspace_id"] == "rw_3f8b01ffbee24ecf9ad3f21e1d2f11ae"
    )
    assert reading_ws["materials"] >= 1

    # 2. Mastery Path
    assert len(state["mastery"]["paths"]) >= 1
    mastery_path = next(
        p for p in state["mastery"]["paths"]
        if p["path_id"] == "topic_cme295_trans_092b939c"
    )
    assert mastery_path["objectives_total"] == 8
    assert mastery_path["stage"] == "learning"

    # 3. Question Bank & Sessions
    assert state["question_bank"]["total"] >= 1
    assert state["sessions"]["active"] >= 1

    # 4. Resources availability
    for resource in state["resources"]:
        assert resource["available"] is True
        assert resource["detail"]

    # 5. Syllabus
    assert state["syllabus"]["total"] == 11
    assert state["syllabus"]["units"][0]["id"] == "lecture_1_transformers"


def test_cme295_timed_media_video_transcript_exists():
    """Verify timed_media transcript exists for Lecture 1 (YouTube 114i2Kz-LZA)."""
    path_service = get_path_service()
    workspace_dir = path_service.get_workspace_dir()
    timed_media_file = workspace_dir / "timed_media" / "3183c03e2de44a547f6d6d8e3509f1df.json"

    assert timed_media_file.exists(), f"Timed media file not found: {timed_media_file}"
    data = json.loads(timed_media_file.read_text(encoding="utf-8"))

    assert data["source"]["provider"] == "youtube"
    assert data["source"]["video_id"] == "114i2Kz-LZA"
    assert data["transcript"]["status"] == "ready"
    assert len(data["transcript"]["cues"]) > 100
