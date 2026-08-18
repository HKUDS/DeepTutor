# End-to-end integration tests for reading a book in both Kids and Adult modes.

from __future__ import annotations

import asyncio
from io import BytesIO
import json
from types import SimpleNamespace
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

import pytest

FastAPI = pytest.importorskip("fastapi").FastAPI
TestClient = pytest.importorskip("fastapi.testclient").TestClient

from deeptutor.immersive_reading.service import ImmersiveReadingService, KidsManager
from deeptutor.services.path_service import PathService


def _create_story_epub() -> bytes:
    """Build a real valid EPUB with 3 illustrated chapters."""
    buf = BytesIO()
    with ZipFile(buf, "w") as zf:
        zf.writestr("mimetype", b"application/epub+zip", compress_type=ZIP_STORED)
        zf.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>""".encode("utf-8"),
            compress_type=ZIP_DEFLATED,
        )

        padding = (
            "The little explorer walked along the winding trail noticing every green leaf and bright flower. "
            * 8
        )
        chap1_html = f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>Chapter 1: The Magic Compass</title></head>
<body>
  <h1>Chapter 1: The Magic Compass</h1>
  <p>Lucas found a shiny brass compass hidden inside the hollow oak tree. {padding}</p>
</body>
</html>"""

        chap2_html = f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>Chapter 2: The Whispering River</title></head>
<body>
  <h1>Chapter 2: The Whispering River</h1>
  <p>At the sparkling river, a friendly blue bird showed Lucas where the stepping stones were safe. {padding}</p>
</body>
</html>"""

        chap3_html = f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>Chapter 3: The Golden Summit</title></head>
<body>
  <h1>Chapter 3: The Golden Summit</h1>
  <p>Reaching the top of the sunny hill, Lucas discovered a treasure chest filled with colorful storybooks. {padding}</p>
</body>
</html>"""

        zf.writestr("OEBPS/chapter1.xhtml", chap1_html.encode("utf-8"), compress_type=ZIP_DEFLATED)
        zf.writestr("OEBPS/chapter2.xhtml", chap2_html.encode("utf-8"), compress_type=ZIP_DEFLATED)
        zf.writestr("OEBPS/chapter3.xhtml", chap3_html.encode("utf-8"), compress_type=ZIP_DEFLATED)

        opf = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="pub-id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="pub-id">urn:uuid:story-12345</dc:identifier>
    <dc:title>The Golden Forest</dc:title>
    <dc:creator>Elena River</dc:creator>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="toc" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
    <item id="c1" href="chapter1.xhtml" media-type="application/xhtml+xml"/>
    <item id="c2" href="chapter2.xhtml" media-type="application/xhtml+xml"/>
    <item id="c3" href="chapter3.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine toc="toc">
    <itemref idref="c1"/>
    <itemref idref="c2"/>
    <itemref idref="c3"/>
  </spine>
</package>"""
        zf.writestr("OEBPS/content.opf", opf.encode("utf-8"), compress_type=ZIP_DEFLATED)

        ncx = """<?xml version="1.0" encoding="utf-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <navMap>
    <navPoint id="np1" playOrder="1">
      <navLabel><text>Chapter 1: The Magic Compass</text></navLabel>
      <content src="chapter1.xhtml"/>
    </navPoint>
    <navPoint id="np2" playOrder="2">
      <navLabel><text>Chapter 2: The Whispering River</text></navLabel>
      <content src="chapter2.xhtml"/>
    </navPoint>
    <navPoint id="np3" playOrder="3">
      <navLabel><text>Chapter 3: The Golden Summit</text></navLabel>
      <content src="chapter3.xhtml"/>
    </navPoint>
  </navMap>
</ncx>"""
        zf.writestr("OEBPS/toc.ncx", ncx.encode("utf-8"), compress_type=ZIP_DEFLATED)

    return buf.getvalue()


@pytest.fixture
def reading_environment(tmp_path, monkeypatch):
    import deeptutor.api.routers.immersive_reading as ir_router
    import deeptutor.api.routers.kids as kids_router
    import deeptutor.api.routers.kids_admin as kids_admin_router
    import deeptutor.immersive_reading.service as service_module

    paths = PathService(workspace_root=tmp_path / "data")
    monkeypatch.setattr(service_module, "get_path_service", lambda: paths)
    monkeypatch.setattr(
        service_module,
        "get_llm_config",
        lambda: SimpleNamespace(
            model="test-model",
            binding="test-binding",
            context_window=128_000,
            max_tokens=4_096,
        ),
    )

    async def mock_llm_fail(**kwargs):
        raise ConnectionError("Offline test")

    monkeypatch.setattr(service_module, "complete", mock_llm_fail)

    ir_service = ImmersiveReadingService()
    kids_manager = KidsManager()

    monkeypatch.setattr(service_module, "get_immersive_reading_service", lambda: ir_service)
    monkeypatch.setattr(service_module, "get_kids_manager", lambda: kids_manager)
    monkeypatch.setattr(kids_router, "get_immersive_reading_service", lambda: ir_service)
    monkeypatch.setattr(kids_router, "get_kids_manager", lambda: kids_manager)
    monkeypatch.setattr(kids_admin_router, "get_immersive_reading_service", lambda: ir_service)
    monkeypatch.setattr(kids_admin_router, "get_kids_manager", lambda: kids_manager)
    monkeypatch.setattr(ir_router, "get_immersive_reading_service", lambda: ir_service)

    app = FastAPI()
    app.include_router(kids_admin_router.router, prefix="/api/v1/kids-admin")
    app.include_router(kids_router.router, prefix="/api/v1/kids")
    app.include_router(ir_router.router, prefix="/api/v1/immersive-reading")

    client = TestClient(app)
    return client, ir_service, kids_manager


def test_full_kids_book_reading_flow(reading_environment) -> None:
    """End-to-end test of the complete child book reading flow."""
    client, ir_service, kids_manager = reading_environment

    # 1. Parent imports real EPUB
    epub_bytes = _create_story_epub()
    doc_summary = ir_service.import_document("golden_forest.epub", epub_bytes)
    doc_id = doc_summary["id"]
    assert doc_summary["title"] == "The Golden Forest"
    assert len(doc_summary["sections"]) == 3

    sec1_id = doc_summary["sections"][0]["id"]
    sec2_id = doc_summary["sections"][1]["id"]
    sec3_id = doc_summary["sections"][2]["id"]

    # 2. Parent creates child profile for Lucas (6 years old, PIN 2026)
    res = client.post(
        "/api/v1/kids-admin/profiles",
        json={
            "name": "Lucas",
            "avatar": "🦁",
            "birth_date": "2020-04-10",
            "help_language": "zh",
            "daily_limit_minutes": 30,
            "parent_pin": "2026",
        },
    )
    assert res.status_code == 200
    profile = res.json()["profile"]
    profile_id = profile["id"]
    assert profile["age_band"] == "6-8"

    # 3. Parent assigns book, only allowing Chapter 1 (index 0) initially
    res = client.post(
        f"/api/v1/kids-admin/profiles/{profile_id}/books",
        json={"document_id": doc_id, "available_through_section_index": 0},
    )
    assert res.status_code == 200

    # 4. Child unlocks session using PIN 2026
    res = client.post(
        "/api/v1/kids/parent-unlock",
        json={"profile_id": profile_id, "pin": "2026"},
    )
    assert res.status_code == 200
    token = res.json()["token"]
    child_headers = {"Authorization": f"Bearer {token}"}

    # 5. Child views their bookshelf
    res = client.get("/api/v1/kids/library", headers={"X-Profile-Id": profile_id})
    assert res.status_code == 200
    shelf = res.json()["library"]
    assert len(shelf) == 1
    assert shelf[0]["document"]["title"] == "The Golden Forest"

    # 6. Child opens the book
    res = client.get(f"/api/v1/kids/books/{doc_id}", headers=child_headers)
    assert res.status_code == 200
    book_data = res.json()
    assert book_data["document"]["title"] == "The Golden Forest"
    # only chapter 1 is allowed
    assert len(book_data["document"]["sections"]) == 1

    # 7. Child reads Chapter 1
    res = client.get(f"/api/v1/kids/books/{doc_id}/sections/{sec1_id}", headers=child_headers)
    assert res.status_code == 200
    content = res.json()["content"]
    assert "shiny brass compass" in content

    # 8. Child translates a word
    async def mock_translate(text, target_language="Chinese"):
        return f"指南针 ({text})"

    ir_service.translate = mock_translate

    res = client.post(
        "/api/v1/kids/translate",
        headers=child_headers,
        json={"text": "compass", "target_language": "Chinese"},
    )
    assert res.status_code == 200
    assert "指南针" in res.json()["translation"]

    # 9. Child completes reading Chapter 1 and records progress
    res = client.put(
        f"/api/v1/kids/books/{doc_id}/progress",
        headers=child_headers,
        json={
            "section_id": sec1_id,
            "section_index": 0,
            "scroll_percent": 100.0,
            "epub_cfi": "epubcfi(/6/2[c1]!/4/2/10)",
            "time_delta": 240.0,
            "completed": True,
        },
    )
    assert res.status_code == 200
    assert sec1_id in res.json()["progress"]["completed_section_ids"]

    # 10. Child takes chapter quiz
    res = client.post(
        f"/api/v1/kids/books/{doc_id}/quiz",
        headers=child_headers,
        json={"section_id": sec1_id},
    )
    assert res.status_code == 200
    questions = res.json()["questions"]
    assert len(questions) >= 1

    # Submit correct answers
    cached_path = ir_service._kids_quiz_path(doc_id, sec1_id)
    with open(cached_path) as f:
        quiz_obj = json.load(f)
    correct_answers = [q["answer_index"] for q in quiz_obj["questions"]]

    res = client.post(
        f"/api/v1/kids/books/{doc_id}/quiz/submit",
        headers=child_headers,
        json={"section_id": sec1_id, "answers": correct_answers},
    )
    assert res.status_code == 200
    grade = res.json()
    assert grade["score"] == len(correct_answers)
    assert grade["stars"] == 3

    # 11. Child tries to jump to Chapter 2 -> blocked (index 1 > available 0)
    res = client.get(f"/api/v1/kids/books/{doc_id}/sections/{sec2_id}", headers=child_headers)
    assert res.status_code == 403

    # 12. Parent views report and unlocks Chapter 2 & 3
    res = client.get(f"/api/v1/kids-admin/profiles/{profile_id}/report")
    assert res.status_code == 200
    report = res.json()
    assert report["total_stars"] == 3
    assert report["books"][0]["progress"]["completed_section_ids"] == [sec1_id]

    # Parent updates assignment to unlock remaining chapters
    res = client.put(
        f"/api/v1/kids-admin/profiles/{profile_id}/books/{doc_id}",
        json={"available_through_section_index": 2},
    )
    assert res.status_code == 200

    # 13. Child can now read Chapter 2
    res = client.get(f"/api/v1/kids/books/{doc_id}/sections/{sec2_id}", headers=child_headers)
    assert res.status_code == 200
    assert "Whispering River" in res.json()["section"]["title"]

    # 14. Child attempts to exit Kids mode
    # Wrong PIN -> rejected
    res = client.post("/api/v1/kids/exit-verify", json={"profile_id": profile_id, "pin": "0000"})
    assert res.status_code == 403

    # Parent enters correct PIN -> success
    res = client.post("/api/v1/kids/exit-verify", json={"profile_id": profile_id, "pin": "2026"})
    assert res.status_code == 200
    assert res.json()["ok"] is True
