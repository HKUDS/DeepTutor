"""Unit and integration tests for Kids Interactive Books (Math and Digital Books)."""

import json

import time
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from deeptutor.book.models import (
    Block,
    BlockType,
    Book,
    BookStatus,
    Chapter,
    Page,
    PageStatus,
    Spine,
)
from deeptutor.book.storage import get_book_storage
from deeptutor.immersive_reading.models import (
    KidsBookAssignment,
    KidsInteractiveBookProgress,
    KidsProfile,
)
from deeptutor.immersive_reading.service import get_kids_manager
import deeptutor.api.routers.kids as kids_router_module
import deeptutor.api.routers.kids_admin as kids_admin_router_module


@pytest.fixture
def clean_kids_manager(tmp_path, monkeypatch):
    manager = get_kids_manager()
    monkeypatch.setattr(manager, "_kids_root", lambda: tmp_path / "kids")
    return manager


@pytest.fixture
def sample_profile(clean_kids_manager) -> KidsProfile:
    return clean_kids_manager.create_profile(
        name="Little Euler",
        birth_date="2018-05-15",
        help_language="zh",
    )


@pytest.fixture
def mock_interactive_book(tmp_path, monkeypatch) -> Book:
    storage = get_book_storage()
    # Mock book root to temporary path
    book_dir = tmp_path / "book_workspace"
    book_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(storage.path_service, "get_book_dir", lambda: book_dir)
    monkeypatch.setattr(storage.path_service, "get_book_root", lambda b_id: book_dir / f"book_{b_id}")
    monkeypatch.setattr(storage.path_service, "ensure_book_root", lambda b_id: (book_dir / f"book_{b_id}") if (book_dir / f"book_{b_id}").mkdir(parents=True, exist_ok=True) is None else (book_dir / f"book_{b_id}"))

    book_id = "math_fun_01"
    book = Book(
        id=book_id,
        title="趣味数学：数与图形",
        description="给小朋友的趣味数学启蒙",
        status=BookStatus.READY,
        page_count=2,
        chapter_count=1,
    )
    storage.save_book(book)

    spine = Spine(
        book_id=book_id,
        chapters=[
            Chapter(
                id="ch_01",
                title="第1章：认识图形与加法",
                summary="图形世界真奇妙",
                order=0,
                page_ids=["pg_01", "pg_02"],
            )
        ],
    )
    storage.save_spine(spine)

    page1 = Page(
        id="pg_01",
        book_id=book_id,
        chapter_id="ch_01",
        title="认识三角形与正方形",
        order=0,
        status=PageStatus.READY,
        blocks=[
            Block(
                id="blk_text_1",
                type=BlockType.TEXT,
                title="图形朋友",
                payload={"text": "三角形有3条边，正方形有4条边！"},
            ),
            Block(
                id="blk_section_1",
                type=BlockType.SECTION,
                payload={
                    "intro": "我们先一起认识身边的图形。",
                    "subsections": [
                        {
                            "heading": "图形藏在哪里",
                            "body": "### 图形藏在哪里\n\nThinking Process:\n\n1. 分析题目。",
                        }
                    ],
                    "bridge_text": "Thinking Process: internal transition",
                },
            ),
            Block(
                id="blk_anim_1",
                type=BlockType.ANIMATION,
                title="图形变变变",
                payload={"video_url": f"book_{book_id}/assets/triangles.mp4", "caption": "看三角形怎么拼成正方形"},
            ),
            Block(
                id="blk_quiz_1",
                type=BlockType.QUIZ,
                title="动手试一试",
                payload={
                    "questions": [
                        {
                            "id": "q1",
                            "question": "三角形有几条边？",
                            "choices": ["2条", "3条", "4条"],
                            "answer_index": 1,
                            "explanation": "三角形有3条边和3个角哦！",
                        }
                    ]
                },
            ),
        ],
    )
    storage.save_page(page1)

    page2 = Page(
        id="pg_02",
        book_id=book_id,
        chapter_id="ch_01",
        title="趣味加法天平",
        order=1,
        status=PageStatus.READY,
        blocks=[
            Block(
                id="blk_text_2",
                type=BlockType.TEXT,
                title="天平平衡",
                payload={"text": "天平两边一样重就会平衡。"},
            )
        ],
    )
    storage.save_page(page2)

    return book


@pytest.fixture
def kids_client(clean_kids_manager, sample_profile, mock_interactive_book) -> TestClient:
    app = FastAPI()
    app.include_router(kids_router_module.router, prefix="/api/v1/kids")
    app.include_router(kids_admin_router_module.router, prefix="/api/v1/kids-admin")
    return TestClient(app)


def test_kids_manager_assign_and_progress(clean_kids_manager, sample_profile, mock_interactive_book):
    """Verify assignment and progress tracking on KidsManager layer."""
    assignment = clean_kids_manager.assign_interactive_book(
        sample_profile.id,
        mock_interactive_book.id,
        available_through_page_order=1,
    )
    assert assignment.content_type == "interactive_book"
    assert assignment.book_id == mock_interactive_book.id
    assert assignment.status == "active"

    # Updating an existing assignment must persist the new unlock boundary.
    updated_assignment = clean_kids_manager.assign_interactive_book(
        sample_profile.id,
        mock_interactive_book.id,
        available_through_page_order=0,
    )
    assert updated_assignment.available_through_page_order == 0
    stored_assignment = next(
        a
        for a in json.loads(clean_kids_manager._assignments_path().read_text(encoding="utf-8"))
        if a["book_id"] == mock_interactive_book.id
    )
    assert stored_assignment["available_through_page_order"] == 0

    # Assignments are global storage; writing for another child must not erase this child.
    second_profile = clean_kids_manager.create_profile(name="Second Child")
    clean_kids_manager.assign_interactive_book(
        second_profile.id,
        mock_interactive_book.id,
        available_through_page_order=0,
    )
    stored_profile_ids = [
        a["profile_id"]
        for a in json.loads(clean_kids_manager._assignments_path().read_text(encoding="utf-8"))
        if a["book_id"] == mock_interactive_book.id
    ]
    assert set(stored_profile_ids) == {sample_profile.id, second_profile.id}

    # Progress tracking
    prog = clean_kids_manager.update_kids_interactive_progress(
        sample_profile.id,
        mock_interactive_book.id,
        page_id="pg_01",
        page_order=0,
        completed=True,
        time_delta=45.0,
    )
    assert prog.current_page_id == "pg_01"
    assert "pg_01" in prog.completed_page_ids
    assert prog.time_spent_seconds >= 45.0

    # Idempotent quiz grading & star awards
    prog, stars1 = clean_kids_manager.record_interactive_quiz_result(
        sample_profile.id, mock_interactive_book.id, "blk_quiz_1", score=1, total=1, earned_stars=3
    )
    assert stars1 == 3
    assert prog.total_stars == 3
    assert prog.quiz_stars_awarded["blk_quiz_1"] == 3

    # Retrying with same score does NOT award duplicate stars
    prog, stars2 = clean_kids_manager.record_interactive_quiz_result(
        sample_profile.id, mock_interactive_book.id, "blk_quiz_1", score=1, total=1, earned_stars=3
    )
    assert stars2 == 0
    assert prog.total_stars == 3


def test_child_interactive_book_endpoints(kids_client, sample_profile, clean_kids_manager, mock_interactive_book):
    """Verify child endpoints: book manifest, sanitized page, quiz grading."""
    # 1. Assign book to profile
    clean_kids_manager.assign_interactive_book(
        sample_profile.id,
        mock_interactive_book.id,
        available_through_page_order=1,
    )

    # 2. Get device token for child
    auth_resp = kids_client.post("/api/v1/kids/select-profile", json={"profile_id": sample_profile.id})
    assert auth_resp.status_code == 200
    token = auth_resp.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 3. Check library listing
    lib_resp = kids_client.get("/api/v1/kids/library", headers={"X-Profile-Id": sample_profile.id})
    assert lib_resp.status_code == 200
    library = lib_resp.json()["library"]
    assert len(library) == 1
    assert library[0]["content_type"] == "interactive_book"
    assert library[0]["book"]["title"] == "趣味数学：数与图形"

    # 4. Get interactive book detail
    book_resp = kids_client.get(f"/api/v1/kids/interactive-books/{mock_interactive_book.id}", headers=headers)
    assert book_resp.status_code == 200
    assert book_resp.json()["book"]["title"] == "趣味数学：数与图形"
    assert len(book_resp.json()["spine"]["chapters"]) == 1

    # 5. Get page content — answers MUST be stripped from quiz block for child safety
    page_resp = kids_client.get(f"/api/v1/kids/interactive-books/{mock_interactive_book.id}/pages/pg_01", headers=headers)
    assert page_resp.status_code == 200
    page_data = page_resp.json()["page"]
    quiz_blk = next(b for b in page_data["blocks"] if b["type"] == "quiz")
    q_data = quiz_blk["payload"]["questions"][0]
    assert "answer_index" not in q_data
    assert "correct_answer" not in q_data
    assert "explanation" not in q_data
    assert q_data["question"] == "三角形有几条边？"
    section_blk = next(b for b in page_data["blocks"] if b["type"] == "section")
    assert section_blk["payload"]["intro"] == "我们先一起认识身边的图形。"
    assert section_blk["payload"]["subsections"][0]["body"] == "### 图形藏在哪里"
    assert "bridge_text" not in section_blk["payload"]
    assert "Thinking Process" not in json.dumps(page_data, ensure_ascii=False)

    # 6. Submit quiz answer — server grades and awards stars
    submit_resp = kids_client.post(
        f"/api/v1/kids/interactive-books/{mock_interactive_book.id}/quiz/submit",
        headers=headers,
        json={"page_id": "pg_01", "block_id": "blk_quiz_1", "answers": [1]},
    )
    assert submit_resp.status_code == 200
    grade = submit_resp.json()
    assert grade["score"] == 1
    assert grade["stars"] == 3
    assert grade["new_stars_awarded"] == 3
    assert grade["per_question"][0]["correct"] is True
    assert "三角形有3条边" in grade["per_question"][0]["explanation"]


def test_parent_admin_interactive_books(kids_client, sample_profile, clean_kids_manager, mock_interactive_book):
    """Verify parent management endpoints for listing and assigning interactive books."""
    # List available books in BookEngine
    list_resp = kids_client.get("/api/v1/kids-admin/available-books")
    assert list_resp.status_code == 200
    books = list_resp.json()["books"]
    assert len(books) >= 1
    assert any(b["id"] == mock_interactive_book.id for b in books)

    # Assign to profile
    assign_resp = kids_client.post(
        f"/api/v1/kids-admin/profiles/{sample_profile.id}/interactive-books",
        json={"book_id": mock_interactive_book.id, "title": "自定义数学书名", "available_through_page_order": 0},
    )
    assert assign_resp.status_code == 200
    assignment = assign_resp.json()["assignment"]
    assert assignment["content_type"] == "interactive_book"
    assert assignment["document_title"] == "自定义数学书名"
