"""Contract tests for the Co-Writer router (`deeptutor/api/routers/co_writer.py`).

Locks the HTTP contract of the collaborative-writing surface: document CRUD
request/response shapes, illegal-payload 4xx handling, and the export/import
failure branches. Storage and the edit agent are stubbed, so nothing here
touches the real workspace or any LLM.
"""

from __future__ import annotations

from pathlib import Path
import re

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

import deeptutor.services.config as _dt_config

_dt_config.load_config_with_main = lambda *_a, **_k: {
    "paths": {},
    "logging": {},
    "system": {"language": "en"},
}

from deeptutor.api.routers import co_writer as co_writer_router
from deeptutor.co_writer import edit_agent
from deeptutor.co_writer.docx_converter import DocxConversionError
from deeptutor.co_writer.storage import CoWriterStorage

MAX_DOC_CHARS = co_writer_router._MAX_DOC_CHARS
MAX_SELECTION_CHARS = co_writer_router._MAX_SELECTION_CHARS
MAX_INSTRUCTION_CHARS = co_writer_router._MAX_INSTRUCTION_CHARS

_DOC_ID_RE = re.compile(r"^[0-9a-f]{8,32}$")


class _StubPathService:
    def __init__(self, root: Path):
        self.root = root

    def get_co_writer_dir(self) -> Path:
        return self.root

    def get_co_writer_history_file(self) -> Path:
        return self.root / "history.json"

    def get_co_writer_tool_calls_dir(self) -> Path:
        return self.root / "tool_calls"

    def get_co_writer_docs_dir(self) -> Path:
        return self.root / "documents"

    def get_co_writer_doc_root(self, doc_id: str) -> Path:
        return self.get_co_writer_docs_dir() / f"doc_{doc_id}"

    def get_co_writer_doc_manifest(self, doc_id: str) -> Path:
        return self.get_co_writer_doc_root(doc_id) / "manifest.json"


class _StubEditAgent:
    """Deterministic stand-in for EditAgent; records every call it receives."""

    def __init__(self):
        self.calls: list[tuple] = []
        self.language = "en"
        self.binding = None
        self.fail_process_with: Exception | None = None
        self.fail_auto_mark_with: Exception | None = None
        self.stream_chunks = ["```markdown\n", "Edited body\n", "```"]

    def refresh_config(self) -> None:
        self.calls.append(("refresh_config",))

    def get_model(self) -> str:
        return "stub-model"

    async def process(self, **kwargs):
        self.calls.append(("process", kwargs))
        if self.fail_process_with is not None:
            raise self.fail_process_with
        return {
            "edited_text": f"edited::{kwargs['text']}",
            "operation_id": "op-edit-0001",
        }

    async def auto_mark(self, *, text):
        self.calls.append(("auto_mark", text))
        if self.fail_auto_mark_with is not None:
            raise self.fail_auto_mark_with
        return {"marked_text": f"marked::{text}", "operation_id": "op-mark-0001"}

    async def gather_context(self, *, source, query, kb_name, operation_id):
        self.calls.append(("gather_context", source, kb_name, query))
        return (f"{source}-context", None)

    async def stream_llm(self, *, user_prompt, system_prompt, stage):
        self.calls.append(("stream_llm", stage, user_prompt, system_prompt))
        for chunk in self.stream_chunks:
            yield chunk


@pytest.fixture()
def storage(tmp_path):
    return CoWriterStorage(path_service=_StubPathService(tmp_path))


@pytest.fixture()
def agent(monkeypatch, tmp_path):
    stub = _StubEditAgent()
    monkeypatch.setattr(co_writer_router, "get_edit_agent", lambda: stub)
    monkeypatch.setattr(
        edit_agent, "get_path_service", lambda: _StubPathService(tmp_path / "agent")
    )
    return stub


@pytest.fixture()
def client(monkeypatch, storage):
    monkeypatch.setattr(co_writer_router, "get_co_writer_storage", lambda: storage)
    app = FastAPI()
    app.include_router(co_writer_router.router)
    with TestClient(app) as test_client:
        yield test_client


# ── Document CRUD: request/response shapes ───────────────────────────────


def test_create_document_returns_full_document_shape(client, storage):
    response = client.post("/documents", json={"title": "My Draft", "content": "# Hi\nBody"})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert set(payload) == {"id", "title", "content", "created_at", "updated_at"}
    assert _DOC_ID_RE.fullmatch(payload["id"])
    assert payload["title"] == "My Draft"
    assert payload["content"] == "# Hi\nBody"
    assert isinstance(payload["created_at"], float)
    assert isinstance(payload["updated_at"], float)
    stored = storage.load_document(payload["id"])
    assert stored is not None and stored.title == "My Draft"


def test_create_document_without_title_derives_it_from_first_heading(client):
    payload = client.post("/documents", json={"content": "# Derived Title\nbody text"}).json()
    assert payload["title"] == "Derived Title"


def test_create_document_with_empty_body_uses_defaults(client):
    response = client.post("/documents", json={})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["title"] == "Untitled draft"
    assert payload["content"] == ""


def test_create_document_rejects_non_string_fields(client):
    assert client.post("/documents", json={"title": 123}).status_code == 422
    assert client.post("/documents", json={"content": ["not", "a", "string"]}).status_code == 422


def test_list_documents_returns_summary_views_without_content(client, storage):
    first = storage.create_document(title="first", content="alpha body")
    second = storage.create_document(title="second", content="beta body")
    storage.update_document(first.id, content="alpha body v2")

    response = client.get("/documents")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert set(payload) == {"documents"}
    summaries = payload["documents"]
    assert {s["id"] for s in summaries} == {first.id, second.id}
    assert summaries[0]["id"] == first.id, "most recently updated document must sort first"
    for summary in summaries:
        assert set(summary) == {"id", "title", "created_at", "updated_at", "preview"}
        assert "content" not in summary


def test_list_documents_truncates_preview_at_160_chars(client, storage):
    storage.create_document(title="long", content="x" * 300)
    summary = client.get("/documents").json()["documents"][0]
    assert summary["preview"].endswith("…")
    assert len(summary["preview"]) <= 161


def test_get_document_returns_persisted_content(client, storage):
    created = storage.create_document(title="Get me", content="# Get\nbody")
    response = client.get(f"/documents/{created.id}")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["id"] == created.id
    assert payload["title"] == "Get me"
    assert payload["content"] == "# Get\nbody"


def test_update_document_applies_title_and_content(client, storage):
    created = storage.create_document(title="Before", content="old body")
    response = client.put(
        f"/documents/{created.id}", json={"title": "After", "content": "new body"}
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["title"] == "After"
    assert payload["content"] == "new body"
    assert storage.load_document(created.id).content == "new body"


def test_update_document_with_empty_object_keeps_fields(client, storage):
    created = storage.create_document(title="Stable", content="keep me")
    before = storage.load_document(created.id)
    response = client.put(f"/documents/{created.id}", json={})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["title"] == "Stable"
    assert payload["content"] == "keep me"
    after = storage.load_document(created.id)
    assert after.updated_at >= before.updated_at


def test_update_document_rejects_non_string_title(client, storage):
    created = storage.create_document(title="Typed", content="body")
    response = client.put(f"/documents/{created.id}", json={"title": [1]})
    assert response.status_code == 422


def test_delete_document_returns_deleted_true_then_404(client, storage):
    created = storage.create_document(title="Doomed", content="body")
    response = client.delete(f"/documents/{created.id}")
    assert response.status_code == 200, response.text
    assert response.json() == {"deleted": True}
    assert storage.load_document(created.id) is None
    assert client.delete(f"/documents/{created.id}").status_code == 404


# ── Unknown / malformed doc ids → 404 on every route ─────────────────────


@pytest.mark.parametrize(
    "bad_id",
    [
        "ffffffffffff",  # well-formed shape, no such document
        "A1B2C3D4E5F6",  # uppercase is not a generated id
        "g1b2c3d4e5f6",  # non-hex
        "abc123",  # too short
        "a" * 40,  # too long
    ],
)
def test_unknown_or_malformed_doc_ids_return_404_on_crud_routes(client, bad_id):
    assert client.get(f"/documents/{bad_id}").status_code == 404
    assert client.put(f"/documents/{bad_id}", json={"title": "x"}).status_code == 404
    assert client.delete(f"/documents/{bad_id}").status_code == 404


def test_not_found_details_name_the_document(client):
    missing = "ffffffffffff"
    assert client.get(f"/documents/{missing}").json()["detail"] == "Document not found"
    assert client.delete(f"/documents/{missing}").json()["detail"] == "Document not found"


# ── Illegal payloads → 4xx before any agent work ─────────────────────────


def test_edit_action_rejects_missing_fields_and_bad_literals(client, agent):
    assert client.post("/documents/actions/edit", json={}).status_code == 422
    assert (
        client.post("/documents/actions/edit", json={"text": "abc"}).status_code == 422
    )  # instruction required
    assert (
        client.post(
            "/documents/actions/edit",
            json={"text": "abc", "instruction": "do", "action": "delete"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/documents/actions/edit",
            json={"text": "abc", "instruction": "do", "source": "books"},
        ).status_code
        == 422
    )
    assert agent.calls == [], "validation failures must never reach the agent"


def test_edit_action_rejects_oversized_text_and_instruction(client, agent):
    response = client.post(
        "/documents/actions/edit",
        json={"text": "x" * (MAX_DOC_CHARS + 1), "instruction": "do"},
    )
    assert response.status_code == 422
    response = client.post(
        "/documents/actions/edit",
        json={"text": "abc", "instruction": "y" * (MAX_INSTRUCTION_CHARS + 1)},
    )
    assert response.status_code == 422
    assert agent.calls == []


def test_react_edit_rejects_invalid_mode_tools_and_oversized_selection(client, agent):
    base = {"selected_text": "abc"}
    assert (
        client.post("/documents/actions/edit-react", json={**base, "mode": "summarize"}).status_code
        == 422
    )
    assert (
        client.post("/documents/actions/edit-react", json={**base, "tools": ["evil"]}).status_code
        == 422
    )
    assert (
        client.post(
            "/documents/actions/edit-react",
            json={"selected_text": "s" * (MAX_SELECTION_CHARS + 1), "instruction": "do"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/documents/actions/edit-react",
            json={"selected_text": "abc", "instruction": "z" * (MAX_INSTRUCTION_CHARS + 1)},
        ).status_code
        == 422
    )
    assert agent.calls == []


def test_react_edit_requires_instruction_when_mode_is_none(client, agent):
    response = client.post(
        "/documents/actions/edit-react",
        json={"selected_text": "abc", "mode": "none", "instruction": "   "},
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert isinstance(detail, str) and detail
    assert agent.calls == []


def test_react_edit_requires_a_non_blank_selection(client, agent):
    response = client.post(
        "/documents/actions/edit-react",
        json={"selected_text": "\n\n  \n", "instruction": "polish"},
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert isinstance(detail, str) and detail
    assert agent.calls == []


def test_react_edit_stream_rejects_bad_payloads_before_streaming(client, agent):
    response = client.post(
        "/documents/actions/edit-react/stream",
        json={"selected_text": "abc", "mode": "none", "instruction": ""},
    )
    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/json")
    assert not response.text.startswith("event:")
    response = client.post(
        "/documents/actions/edit-react/stream",
        json={"selected_text": "abc", "mode": "bogus"},
    )
    assert response.status_code == 422
    assert agent.calls == []


def test_export_docx_rejects_oversized_content(client):
    response = client.post(
        "/documents/export/docx",
        json={"title": "big", "content": "x" * (MAX_DOC_CHARS + 1)},
    )
    assert response.status_code == 422


def test_import_docx_rejects_missing_unsupported_and_empty_files(client, storage):
    doc = client.post(
        "/documents/import/docx",
        files={"file": ("legacy.doc", b"OLE2", "application/msword")},
    )
    assert doc.status_code == 400
    assert "docx" in doc.json()["detail"].lower()

    txt = client.post(
        "/documents/import/docx",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert txt.status_code == 400

    empty = client.post(
        "/documents/import/docx",
        files={
            "file": (
                "empty.docx",
                b"",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert empty.status_code == 400
    assert "empty" in empty.json()["detail"].lower()
    assert storage.list_documents() == []


# ── Export / import failure branches ─────────────────────────────────────


def test_export_docx_returns_400_when_converter_reports_bad_input(client, monkeypatch):
    def _raise(content, title):
        raise DocxConversionError("simulated converter rejection")

    monkeypatch.setattr(co_writer_router, "markdown_to_docx", _raise)
    response = client.post("/documents/export/docx", json={"title": "T", "content": "# hi"})
    assert response.status_code == 400
    assert "simulated converter rejection" in response.json()["detail"]


def test_export_docx_returns_500_on_unexpected_converter_error(client, monkeypatch):
    def _raise(content, title):
        raise RuntimeError("converter exploded")

    monkeypatch.setattr(co_writer_router, "markdown_to_docx", _raise)
    response = client.post("/documents/export/docx", json={"title": "T", "content": "# hi"})
    assert response.status_code == 500
    assert "converter exploded" in response.json()["detail"]


def test_export_docx_sanitizes_unsafe_title_in_content_disposition(client):
    response = client.post(
        "/documents/export/docx",
        json={"title": 'a"b/c:d*e?f<g>h|i', "content": "# hi"},
    )
    assert response.status_code == 200, response.text
    disposition = response.headers["content-disposition"]
    assert 'filename="a-b-c-d-e-f-g-h-i.docx"' in disposition


def test_import_docx_returns_400_for_corrupt_upload(client, storage):
    response = client.post(
        "/documents/import/docx",
        files={"file": ("broken.docx", b"not-a-real-docx", "application/octet-stream")},
    )
    assert response.status_code == 400
    assert storage.list_documents() == []


def test_import_docx_returns_500_on_unexpected_conversion_error(client, monkeypatch):
    def _raise(data, filename):
        raise RuntimeError("parser exploded")

    monkeypatch.setattr(co_writer_router, "docx_to_markdown", _raise)
    response = client.post(
        "/documents/import/docx",
        files={"file": ("ok.docx", b"PK\x03\x04payload", "application/octet-stream")},
    )
    assert response.status_code == 500
    assert "parser exploded" in response.json()["detail"]


# ── Edit actions: agent request/response contracts ───────────────────────


def test_edit_action_forwards_request_fields_to_agent(client, agent):
    response = client.post(
        "/documents/actions/edit",
        json={
            "text": "draft text",
            "instruction": "make it shorter",
            "action": "shorten",
            "source": None,
            "kb_name": None,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json() == {
        "edited_text": "edited::draft text",
        "operation_id": "op-edit-0001",
    }
    assert agent.calls[0] == (
        "process",
        {
            "text": "draft text",
            "instruction": "make it shorter",
            "action": "shorten",
            "source": None,
            "kb_name": None,
        },
    )


def test_edit_action_maps_agent_exception_to_500(client, agent):
    agent.fail_process_with = ValueError("boom")
    response = client.post("/documents/actions/edit", json={"text": "abc", "instruction": "do"})
    assert response.status_code == 500
    assert "boom" in response.json()["detail"]


def test_automark_forwards_text_and_returns_payload(client, agent):
    response = client.post("/documents/actions/automark", json={"text": "mark me"})
    assert response.status_code == 200, response.text
    assert response.json() == {
        "marked_text": "marked::mark me",
        "operation_id": "op-mark-0001",
    }
    assert agent.calls[0] == ("auto_mark", "mark me")


def test_automark_maps_agent_exception_to_500(client, agent):
    agent.fail_auto_mark_with = RuntimeError("nope")
    response = client.post("/documents/actions/automark", json={"text": "mark me"})
    assert response.status_code == 500
    assert "nope" in response.json()["detail"]


def test_react_edit_strips_output_fence_and_reports_tools_used(client, agent):
    response = client.post(
        "/documents/actions/edit-react",
        json={"selected_text": "source text", "instruction": "shorten", "tools": ["web"]},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert set(payload) == {"edited_text", "operation_id", "tools_used"}
    assert payload["edited_text"] == "Edited body"
    assert payload["tools_used"] == ["web"]
    assert _DOC_ID_RE_OR_TIMESTAMP(payload["operation_id"])
    gathered = [call for call in agent.calls if call[0] == "gather_context"]
    assert gathered == [("gather_context", "web", None, "shorten")]


def test_react_edit_skips_rag_tool_without_kb_name_and_deduplicates(client, agent):
    response = client.post(
        "/documents/actions/edit-react",
        json={
            "selected_text": "abc",
            "instruction": "do",
            "mode": "rewrite",
            "tools": ["rag", "web", "rag", "web"],
        },
    )
    assert response.status_code == 200, response.text
    gathered = [call for call in agent.calls if call[0] == "gather_context"]
    assert [call[1] for call in gathered] == ["web"], (
        "rag without kb_name must be skipped; duplicate tools must be deduplicated"
    )


def test_react_edit_forwards_kb_name_to_rag_gather(client, agent, monkeypatch):
    import deeptutor.services.rag.pipelines.pageindex as pageindex

    monkeypatch.setattr(pageindex, "is_pageindex_kb", lambda kb_name: False)
    response = client.post(
        "/documents/actions/edit-react",
        json={
            "selected_text": "abc",
            "instruction": "cite",
            "tools": ["rag"],
            "kb_name": "my-kb",
        },
    )
    assert response.status_code == 200, response.text
    gathered = [call for call in agent.calls if call[0] == "gather_context"]
    assert gathered == [("gather_context", "rag", "my-kb", "cite")]
    assert response.json()["tools_used"] == ["rag"]


def test_react_edit_records_history_entry(client, agent, tmp_path):
    response = client.post(
        "/documents/actions/edit-react",
        json={"selected_text": "abc", "instruction": "do", "mode": "expand"},
    )
    assert response.status_code == 200, response.text
    operation_id = response.json()["operation_id"]
    history = edit_agent.load_history()
    entry = next(item for item in history if item.get("id") == operation_id)
    assert entry["action"] == "react_edit"
    assert entry["mode"] == "expand"
    assert entry["output"]["edited_text"] == "Edited body"


# ── History and tool-call endpoints ──────────────────────────────────────


def test_history_endpoints_return_recorded_operations(client, agent):
    edit_agent.append_history({"id": "op-1", "action": "react_edit"})
    edit_agent.append_history({"id": "op-2", "action": "react_edit"})

    listing = client.get("/documents/history")
    assert listing.status_code == 200, listing.text
    payload = listing.json()
    assert set(payload) == {"history", "total"}
    assert payload["total"] == 2
    assert [item["id"] for item in payload["history"]] == ["op-1", "op-2"]

    single = client.get("/documents/history/op-2")
    assert single.status_code == 200, single.text
    assert single.json()["id"] == "op-2"

    missing = client.get("/documents/history/op-404")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Operation not found"


def test_tool_call_endpoint_serves_recorded_payload(client, agent, tmp_path):
    tool_calls_dir = edit_agent.tool_calls_dir()
    tool_calls_dir.mkdir(parents=True, exist_ok=True)
    (tool_calls_dir / "op-9_details.json").write_text(
        '{"id": "op-9", "tool": "web"}', encoding="utf-8"
    )

    found = client.get("/documents/tool-calls/op-9")
    assert found.status_code == 200, found.text
    assert found.json() == {"id": "op-9", "tool": "web"}

    missing = client.get("/documents/tool-calls/op-404")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Tool call not found"


def _DOC_ID_RE_OR_TIMESTAMP(operation_id: str) -> bool:
    # operation ids are `<YYYYmmdd_HHMMSS>_<6 hex chars>`
    return bool(re.fullmatch(r"\d{8}_\d{6}_[0-9a-f]{6}", operation_id))
