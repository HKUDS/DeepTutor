"""Unit tests for KidsManager, profile management, and sight words."""

from __future__ import annotations

import datetime
from pathlib import Path
import pytest

from deeptutor.immersive_reading.service import (
    ImmersiveReadingService,
    KidsManager,
)
from deeptutor.immersive_reading.sight_words import (
    VOCAB_3_5,
    VOCAB_6_8_EXTRA,
    VOCAB_9_12_EXTRA,
    generate_translation_quiz,
)
from deeptutor.services.path_service import PathService


@pytest.fixture
def test_env(tmp_path, monkeypatch):
    import deeptutor.immersive_reading.service as service_module

    paths = PathService(workspace_root=tmp_path / "data")
    monkeypatch.setattr(service_module, "get_path_service", lambda: paths)

    ir_service = ImmersiveReadingService()
    kids_manager = KidsManager()
    monkeypatch.setattr(service_module, "get_immersive_reading_service", lambda: ir_service)
    monkeypatch.setattr(service_module, "get_kids_manager", lambda: kids_manager)
    return ir_service, kids_manager


def test_profile_creation_and_age_band_calculation(test_env) -> None:
    _, kids_manager = test_env
    today = datetime.date.today()
    birth_5yo = (today - datetime.timedelta(days=5 * 365 + 30)).isoformat()
    p5 = kids_manager.create_profile(
        name="Little Fox",
        avatar="🦊",
        birth_date=birth_5yo,
        help_language="zh",
        daily_limit_minutes=20,
        parent_pin="1234",
    )
    assert p5.name == "Little Fox"
    assert p5.avatar == "🦊"
    assert p5.age == 5
    assert p5.age_band == "3-5"
    assert p5.help_language == "zh"
    assert p5.daily_limit_minutes == 20
    assert kids_manager.has_pin(p5.id) is True

    birth_7yo = (today - datetime.timedelta(days=7 * 365 + 30)).isoformat()
    p7 = kids_manager.create_profile(
        name="Panda",
        avatar="🐼",
        birth_date=birth_7yo,
        parent_pin="",
    )
    assert p7.age == 7
    assert p7.age_band == "6-8"
    assert kids_manager.has_pin(p7.id) is False

    birth_10yo = (today - datetime.timedelta(days=10 * 365 + 30)).isoformat()
    p10 = kids_manager.create_profile(
        name="Dragon",
        avatar="🐉",
        birth_date=birth_10yo,
    )
    assert p10.age == 10
    assert p10.age_band == "9-12"


def test_pin_verification_and_lockout(test_env) -> None:
    _, kids_manager = test_env
    profile = kids_manager.create_profile(
        name="Mia",
        birth_date="2019-01-01",
        parent_pin="8888",
    )

    assert kids_manager.verify_parent_pin(profile.id, "8888") is True
    assert kids_manager.verify_parent_pin(profile.id, "0000") is False
    assert kids_manager.verify_parent_pin(profile.id, "1234") is False


def test_profile_update_and_deletion(test_env) -> None:
    _, kids_manager = test_env
    profile = kids_manager.create_profile(
        name="Sam",
        avatar="🐶",
        birth_date="2018-05-20",
    )
    assert profile.name == "Sam"

    updated = kids_manager.update_profile(
        profile.id,
        name="Sammy",
        avatar="🦁",
        daily_limit_minutes=45,
    )
    assert updated.name == "Sammy"
    assert updated.avatar == "🦁"
    assert updated.daily_limit_minutes == 45

    profiles = kids_manager.list_profiles()
    assert len(profiles) == 1
    assert profiles[0].id == profile.id

    kids_manager.delete_profile(profile.id)
    assert kids_manager.list_profiles() == []
    assert kids_manager.get_profile(profile.id) is None


def test_book_assignment_and_chapter_gating(test_env) -> None:
    ir_service, kids_manager = test_env
    doc = ir_service.import_document(
        "story.txt",
        b"# Chapter 1\nContent 1\n# Chapter 2\nContent 2\n# Chapter 3\nContent 3"
    )
    profile = kids_manager.create_profile(name="Leo", birth_date="2018-01-01")

    assignment = kids_manager.assign_book(
        profile.id,
        document_id=doc["id"],
        available_through_section_index=1,
    )
    assert assignment.profile_id == profile.id
    assert assignment.document_id == doc["id"]
    assert assignment.status == "active"
    assert assignment.available_through_section_index == 1

    assert kids_manager.is_section_allowed(profile.id, doc["id"], 0) is True
    assert kids_manager.is_section_allowed(profile.id, doc["id"], 1) is True
    assert kids_manager.is_section_allowed(profile.id, doc["id"], 2) is False

    kids_manager.update_assignment(
        profile.id,
        doc["id"],
        available_through_section_index=2,
    )
    assert kids_manager.is_section_allowed(profile.id, doc["id"], 2) is True

    kids_manager.unassign_book(profile.id, doc["id"])
    assert kids_manager.is_section_allowed(profile.id, doc["id"], 0) is False


def test_progress_stars_and_quiz_recording(test_env) -> None:
    ir_service, kids_manager = test_env
    doc = ir_service.import_document(
        "fairytale.txt",
        b"# Chapter 1\nOnce upon a time in a magical forest.\n# Chapter 2\nThe brave little bird found a golden key."
    )
    profile = kids_manager.create_profile(name="Amy", birth_date="2019-02-15")
    kids_manager.assign_book(profile.id, doc["id"])

    p0 = kids_manager.load_kids_progress(profile.id, doc["id"])
    assert p0.total_stars == 0
    assert p0.completed_section_ids == []

    sec_id = doc["sections"][0]["id"]
    kids_manager.update_kids_progress_record(
        profile.id,
        doc["id"],
        section_id=sec_id,
        section_index=0,
        scroll_percent=85.0,
        epub_cfi="epubcfi(/6/4[chap1]!/4/2/10)",
        time_delta=120.0,
    )
    kids_manager.mark_section_completed(profile.id, doc["id"], sec_id)

    kids_manager.add_stars(profile.id, doc["id"], 3)
    kids_manager.record_quiz(profile.id, doc["id"], score=3, total=3)

    p1 = kids_manager.load_kids_progress(profile.id, doc["id"])
    assert p1.current_section_id == sec_id
    assert p1.scroll_percent == 85.0
    assert p1.completed_section_ids == [sec_id]
    assert p1.total_stars == 3
    assert p1.quiz_attempts == 1
    assert p1.quiz_best_score == 3
    assert p1.time_spent_seconds >= 120.0

    report = kids_manager.get_report(profile.id)
    assert report["profile"]["name"] == "Amy"
    assert report["total_stars"] == 3
    assert report["total_books"] == 1
    assert len(report["books"]) == 1
    assert report["books"][0]["document"]["id"] == doc["id"]
    assert report["books"][0]["progress"]["completed_section_ids"] == [sec_id]


def test_sight_words_fallback_quiz_generation() -> None:
    text_sample = """
    The little dog and the happy cat played under the big sun.
    The blue sky was warm and the green tree was tall.
    They decided to jump and run around the house.
    """
    questions_3_5 = generate_translation_quiz(text_sample, age_band="3-5")
    assert len(questions_3_5) >= 1
    for q in questions_3_5:
        assert q["kind"] == "sight_word"
        assert len(q["choices"]) == 4
        assert 0 <= q["answer_index"] < 4
        assert q["explanation"]

    assert len(VOCAB_3_5) > 30
    assert len(VOCAB_6_8_EXTRA) > 30
    assert len(VOCAB_9_12_EXTRA) > 30
