from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

import deeptutor.api.routers.kids as kids_router_module
from deeptutor.immersive_reading.models import KidsBookAssignment, KidsLearnResult
from deeptutor.immersive_reading.service import _write_json, get_kids_manager

SECTION_TEXT = "量子世界和我们每天看见的世界不一样。科学家用量子力学研究很小的粒子。"


class FakeLearnReadingService:
    def load_document(self, document_id: str):
        assert document_id == "readingdoc001"
        return SimpleNamespace(
            sections=[
                SimpleNamespace(
                    id="section-1",
                    title="第1讲 量子世界",
                    index=0,
                    checkpoint_kind="chapter",
                )
            ]
        )

    def get_section(self, document_id: str, section_id: str):
        assert document_id == "readingdoc001"
        assert section_id == "section-1"
        return {"content": SECTION_TEXT}

    async def generate_kids_learn(self, document_id, section_id, visible_text, **kwargs):
        assert document_id == "readingdoc001"
        assert section_id == "section-1"
        assert visible_text in SECTION_TEXT
        assert kwargs["language"] == "zh"
        return KidsLearnResult(
            document_id=document_id,
            section_id=section_id,
            overview="这一页介绍量子世界。",
            concepts=[],
            reflection={
                "prompt": "用自己的话说说这一页。",
                "hint": "先看第一句。",
                "answer": "这一页介绍量子世界。",
            },
            language="zh",
            source="fallback",
        )


def learn_client(tmp_path, monkeypatch):
    manager = get_kids_manager()
    monkeypatch.setattr(manager, "_kids_root", lambda: tmp_path / "kids")
    profile = manager.create_profile(name="Reader", help_language="zh")
    _write_json(
        manager._assignments_path(),
        [
            KidsBookAssignment(
                id="assignment001",
                profile_id=profile.id,
                document_id="readingdoc001",
                document_title="量子世界",
            ).model_dump(mode="json")
        ],
    )
    monkeypatch.setattr(
        kids_router_module,
        "get_immersive_reading_service",
        lambda: FakeLearnReadingService(),
    )
    app = FastAPI()
    app.include_router(kids_router_module.router, prefix="/api/v1/kids")
    client = TestClient(app)
    selected = client.post("/api/v1/kids/select-profile", json={"profile_id": profile.id})
    headers = {"Authorization": f"Bearer {selected.json()['token']}"}
    return client, headers


def test_kids_learn_requires_session_and_anchored_page(tmp_path, monkeypatch):
    client, headers = learn_client(tmp_path, monkeypatch)
    endpoint = "/api/v1/kids/books/readingdoc001/learn"

    # Profile selection now mirrors the device token into an HttpOnly cookie
    # for storage-restricted browsers. Remove it to exercise the anonymous
    # request while retaining the explicit bearer token for later assertions.
    client.cookies.clear()
    unauthenticated = client.post(
        endpoint, json={"section_id": "section-1", "visible_text": SECTION_TEXT}
    )
    assert unauthenticated.status_code == 401

    unanchored = client.post(
        endpoint,
        json={"section_id": "section-1", "visible_text": "这是一个完全无关的故事。"},
        headers=headers,
    )
    assert unanchored.status_code == 400

    anchored = client.post(
        endpoint,
        json={"section_id": "section-1", "visible_text": SECTION_TEXT},
        headers=headers,
    )
    assert anchored.status_code == 200
    payload = anchored.json()
    assert payload["language"] == "zh"
    assert payload["source"] == "fallback"
    assert payload["reflection"]["answer"]


def test_kids_learn_anchors_with_newlines_and_spaces_in_cjk(tmp_path, monkeypatch):
    client, headers = learn_client(tmp_path, monkeypatch)
    endpoint = "/api/v1/kids/books/readingdoc001/learn"

    # Browser visible text is without newlines, while section text has newlines
    browser_text = "量子世界和我们每天看见的世界不一样。"
    response = client.post(
        endpoint,
        json={"section_id": "section-1", "visible_text": browser_text},
        headers=headers,
    )
    assert response.status_code == 200


def test_kids_learn_resolves_section_from_visible_text_when_section_id_mismatched(
    tmp_path, monkeypatch
):
    client, headers = learn_client(tmp_path, monkeypatch)
    endpoint = "/api/v1/kids/books/readingdoc001/learn"

    # Client sends empty section_id
    response = client.post(
        endpoint,
        json={"section_id": "", "visible_text": SECTION_TEXT},
        headers=headers,
    )
    assert response.status_code == 200
