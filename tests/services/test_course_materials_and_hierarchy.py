"""Tests for course materials, resources, and deep-nesting syllabus hierarchy."""

from __future__ import annotations

import re
import pytest

from deeptutor.services.courses import get_course_service
from deeptutor.services.courses_state import build_course_state


@pytest.mark.asyncio
async def test_course_hierarchy_has_nested_unit_concepts():
    """Verify that Course -> Lecture -> Unit has 4th-tier sub-concepts parsed cleanly."""
    service = get_course_service()
    course = service.get("course_ad839270ec36")
    assert course is not None

    lecture_1 = next(u for u in course.syllabus if u.id == "lecture_1_transformers")
    assert len(lecture_1.topics) == 8

    # Check that Lecture 1 Unit 1 contains sub-concepts
    unit_1_topic = lecture_1.topics[0]
    match = re.search(r"\((.*?)\)", unit_1_topic)
    assert match is not None, f"Expected parenthesized concepts in: {unit_1_topic}"
    concepts = [c.strip() for c in match.group(1).split("·")]
    assert "NLP Overview" in concepts
    assert "Language Modeling" in concepts

    # Check Lecture 2 Unit 1 contains sub-concepts
    lecture_2 = next(u for u in course.syllabus if u.id == "lecture_2_llms")
    unit_2_topic = lecture_2.topics[0]
    match_2 = re.search(r"\((.*?)\)", unit_2_topic)
    assert match_2 is not None
    concepts_2 = [c.strip() for c in match_2.group(1).split("·")]
    assert "Encoder-only" in concepts_2


@pytest.mark.asyncio
async def test_course_state_maintains_all_connections():
    """Verify full state connectivity across all 4 learning surfaces."""
    state = await build_course_state("course_ad839270ec36")

    # Reading workspace connected
    assert any(ws["workspace_id"] == "rw_3f8b01ffbee24ecf9ad3f21e1d2f11ae" for ws in state["reading"]["workspaces"])

    # Mastery path connected
    assert any(p["path_id"] == "topic_cme295_trans_092b939c" for p in state["mastery"]["paths"])

    # Notebook connected
    assert any(r["kind"] == "notebook" and r["available"] for r in state["resources"])

    # Question Bank connected
    assert state["question_bank"]["total"] >= 1
    assert state["sessions"]["active"] >= 1
