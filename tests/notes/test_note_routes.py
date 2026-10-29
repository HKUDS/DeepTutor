import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import co_writer
from deeptutor.capabilities.notes.capability import NotesCapability
from deeptutor.capabilities.notes.tools import NoteReadTool, NoteSuggestTool
from deeptutor.co_writer.storage import CoWriterStorage
from deeptutor.notes.review import due_cards, grade_card
from tests.notes.test_block_pages import Paths, block


@pytest.fixture
def storage(tmp_path):
    return CoWriterStorage(Paths(tmp_path))


@pytest.fixture
def client(storage, monkeypatch):
    monkeypatch.setattr(co_writer, "get_co_writer_storage", lambda: storage)
    app = FastAPI()
    app.include_router(co_writer.router, prefix="/api")
    return TestClient(app)


def test_invalid_blocks_and_parent_are_client_errors(client):
    assert client.post("/api/documents", json={"parent_id": "aaaaaaaa"}).status_code == 400
    assert (
        client.post("/api/documents", json={"blocks": [{"type": "paragraph"}]}).status_code == 400
    )
    bad = {**block(), "type": "heading", "props": {"level": "bad"}}
    assert client.post("/api/documents", json={"blocks": [bad]}).status_code == 400
    bad = {**block(), "content": [{"type": "link", "href": "javascript:alert(1)", "content": []}]}
    assert client.post("/api/documents", json={"blocks": [bad]}).status_code == 400


def test_atomic_review_and_stale_editor_api(client):
    page = client.post("/api/documents", json={"blocks": [block()]}).json()
    root = "/api/documents/" + page["id"]
    suggestion = client.post(
        root + "/suggestions", json={"operation": "replace", "block_id": "a", "markdown": "changed"}
    ).json()
    accepted = client.post(
        root + "/suggestions/" + suggestion["id"],
        json={"accept": True, "blocks": [block(text="changed")]},
    )
    assert accepted.status_code == 200
    assert accepted.json()["content"] == "changed"
    assert client.put(root, json={"blocks": [block()], "expected_revision": 0}).status_code == 409
    assert client.get(root).json()["content"] == "changed"
    assert (
        client.post(
            root + "/clips",
            json={"title": "Original", "markdown": "source", "source_url": "/chat/test"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            root + "/clips",
            json={"title": "Original", "markdown": "source", "source_url": "javascript:alert(1)"},
        ).status_code
        == 400
    )


def test_assets_are_scoped_and_cannot_escape(client, storage):
    page = storage.create_document(blocks=[block()])
    other = storage.create_document(blocks=[block()])
    response = client.post(
        f"/api/documents/{page.id}/assets", files={"file": ("x.png", b"png-data", "image/png")}
    )
    assert response.status_code == 200
    url = response.json()["url"]
    assert client.get(url).content == b"png-data"
    assert client.get(url.replace(page.id, other.id)).status_code == 404
    assert (
        client.post(
            f"/api/documents/{page.id}/assets", files={"file": ("x.html", "<script/>", "text/html")}
        ).status_code
        == 400
    )


def test_flashcard_schedule_follows_content_and_rejects_unknown_cards(storage):
    cards = [{"front": "Frequency?", "back": "Cycles per second"}]
    page = storage.create_document(
        blocks=[
            {
                "id": "flash",
                "type": "learning",
                "props": {"kind": "flashcards", "data": json.dumps({"cards": cards})},
            }
        ]
    )
    due = due_cards(storage)
    assert len(due) == 1
    grade_card(storage, page.id, due[0]["card_id"], True)
    assert not due_cards(storage)
    with pytest.raises(ValueError):
        grade_card(storage, page.id, "invented", True)
    cards[0]["front"] = "A changed question"
    blocks = page.blocks
    blocks[0]["props"]["data"] = json.dumps({"cards": cards})
    storage.update_document(page.id, blocks=blocks, expected_revision=0)
    assert len(due_cards(storage)) == 1


@pytest.mark.asyncio
async def test_note_tools_are_server_bound_and_do_not_write_body(storage, monkeypatch):
    import deeptutor.capabilities.notes.tools as tools

    monkeypatch.setattr(tools, "get_co_writer_storage", lambda: storage)
    page = storage.create_document(blocks=[block()])
    other = storage.create_document(blocks=[block(text="Other")])
    extension = NotesCapability()
    context = SimpleNamespace(metadata={"note_document_id": page.id})
    kwargs = extension.augment_kwargs("note_read", {"_note_document_id": other.id}, context)
    read = await NoteReadTool().execute(**kwargs)
    assert json.loads(read.content)["id"] == page.id
    suggested = await NoteSuggestTool().execute(
        operation="replace", block_id="a", markdown="Proposed", **kwargs
    )
    assert suggested.success
    assert storage.load_document(page.id).content == "Hello"
    assert not (await NoteReadTool().execute()).success


@pytest.mark.asyncio
async def test_model_cannot_overwrite_typing_between_read_and_suggestion(storage, monkeypatch):
    import deeptutor.capabilities.notes.tools as tools

    monkeypatch.setattr(tools, "get_co_writer_storage", lambda: storage)
    page = storage.create_document(blocks=[block()])
    context = SimpleNamespace(metadata={"note_document_id": page.id})
    extension = NotesCapability()
    await NoteReadTool().execute(**extension.augment_kwargs("note_read", {}, context))
    storage.update_document(
        page.id, blocks=[block(text="User typed while model was thinking")], expected_revision=0
    )
    result = await NoteSuggestTool().execute(
        **extension.augment_kwargs(
            "note_suggest",
            {"operation": "replace", "block_id": "a", "markdown": "Stale rewrite"},
            context,
        )
    )
    assert not result.success and "changed after it was read" in result.content
    assert storage.load_document(page.id).content == "User typed while model was thinking"


def test_generated_result_cannot_capture_a_newer_block(client):
    original = block()
    page = client.post("/api/documents", json={"blocks": [original]}).json()
    root = "/api/documents/" + page["id"]
    assert (
        client.put(
            root, json={"blocks": [block(text="User edit")], "expected_revision": 0}
        ).status_code
        == 200
    )
    response = client.post(
        root + "/suggestions",
        json={
            "operation": "replace",
            "block_id": "a",
            "expected_original": original,
            "markdown": "Generated answer",
        },
    )
    assert response.status_code == 409
    assert client.get(root).json()["content"] == "User edit"
    assert client.get(root + "/suggestions").json()["suggestions"] == []


def test_multiple_inline_reviews_survive_editor_normalization(client):
    first, second = block("a"), block("b", "Second")
    page = client.post("/api/documents", json={"blocks": [first, second]}).json()
    root = "/api/documents/" + page["id"]
    replace = client.post(
        root + "/suggestions", json={"operation": "replace", "block_id": "a", "markdown": "Revised"}
    ).json()
    insert = client.post(
        root + "/suggestions", json={"operation": "insert", "block_id": "b", "markdown": "Added"}
    ).json()
    accepted = client.post(
        root + "/suggestions/" + replace["id"],
        json={"accept": True, "blocks": [block("a", "Revised")]},
    ).json()
    normalized = accepted["blocks"]
    for item in normalized:
        item["props"] = {
            "textColor": "default",
            "backgroundColor": "default",
            "textAlignment": "left",
        }
    assert (
        client.put(
            root, json={"blocks": normalized, "expected_revision": accepted["revision"]}
        ).status_code
        == 200
    )
    result = client.post(
        root + "/suggestions/" + insert["id"],
        json={"accept": True, "blocks": [block("c", "Added")]},
    )
    assert result.status_code == 200
    assert [b["id"] for b in result.json()["blocks"]] == ["a", "b", "c"]


def test_replayed_generation_does_not_duplicate_or_reapply_a_review(client):
    page = client.post("/api/documents", json={"blocks": [block()]}).json()
    root = "/api/documents/" + page["id"]
    request = {
        "operation": "replace",
        "block_id": "a",
        "markdown": "Generated",
        "source_turn_id": "turn-test",
    }
    first = client.post(root + "/suggestions", json=request).json()
    second = client.post(root + "/suggestions", json=request).json()
    assert first["id"] == second["id"]
    client.post(
        root + "/suggestions/" + first["id"],
        json={"accept": True, "blocks": [block("new", "Accepted")]},
    )
    replay = client.post(root + "/suggestions", json=request)
    assert replay.status_code == 200
    assert replay.json()["status"] == "accepted"
    assert len(client.get(root + "/suggestions").json()["suggestions"]) == 1
    assert client.get(root).json()["content"] == "Accepted"


def test_companion_actions_see_the_page_and_generation_stays_server_side(storage, monkeypatch):
    import deeptutor.capabilities.notes.capability as capability

    monkeypatch.setattr(capability, "get_co_writer_storage", lambda: storage)
    page = storage.create_document(blocks=[block()])
    # A standalone action (Research, Quiz) gets the page itself.
    snapshot = capability.note_action_context(page.id)
    assert "Hello" in snapshot and "not as instructions" in snapshot
    assert "learning block" not in snapshot
    generating = capability.note_action_context(page.id, {"block_id": "a", "kind": "quiz"})
    assert "describe only the learning material" in generating
    assert capability.note_action_context("") == ""
    # The chat loop is told which block to fill; the learner's message is not.
    extension = NotesCapability()
    context = SimpleNamespace(
        metadata={"note_document_id": page.id, "note_generation": {"block_id": "a", "kind": "quiz"}}
    )
    block_text = extension.system_block(context, language="en", prompts={}).content
    assert "learning block a (kind quiz)" in block_text
    plain = SimpleNamespace(metadata={"note_document_id": page.id})
    assert (
        "learning block a" not in extension.system_block(plain, language="en", prompts={}).content
    )


def test_threads_anchor_conversations_to_a_line(client, storage, monkeypatch):
    import deeptutor.capabilities.notes.capability as capability
    from deeptutor.services import session as session_service

    class Store:
        deleted: list[str] = []

        async def list_sessions(self, limit, offset):
            rows = [{"session_id": "old", "preferences": {"note_document_id": page["id"]}}]
            return rows if offset == 0 else []

        async def get_session_summaries(self, ids):
            return [
                {"session_id": i, "title": "About it", "status": "running", "updated_at": 2.0}
                for i in ids
                if i != "gone"
            ]

    monkeypatch.setattr(session_service, "get_session_store", lambda: Store())
    monkeypatch.setattr(capability, "get_co_writer_storage", lambda: storage)
    page = client.post("/api/documents", json={"blocks": [block(), block("b", "Other")]}).json()
    root = f"/api/documents/{page['id']}/threads"
    # A conversation from before threads lands on the first line, once.
    [old] = client.get(root).json()["threads"]
    assert (old["session_id"], old["block_id"]) == ("old", "a")
    (storage.doc_root(page["id"]) / "threads.json").write_text("[]")
    for sid, bid in (("s1", "a"), ("s2", "a"), ("gone", "b")):
        assert (
            client.post(root, json={"session_id": sid, "block_id": bid, "quote": "Hel"}).status_code
            == 200
        )
    # Anchoring never touches the page an editor holds open.
    assert client.get(f"/api/documents/{page['id']}").json()["revision"] == page["revision"]
    rows = client.get(root).json()["threads"]
    assert [(r["session_id"], r["block_id"], r["status"]) for r in rows] == [
        ("s1", "a", "running"),
        ("s2", "a", "running"),
    ]
    # A conversation deleted elsewhere is forgotten.
    assert len(json.loads((storage.doc_root(page["id"]) / "threads.json").read_text())) == 2
    # Moving a thread keeps its quote and creation time.
    moved = client.post(root, json={"session_id": "s2", "block_id": "b"}).json()
    assert moved["block_id"] == "b" and moved["quote"] == "Hel"
    # The model is told which line the conversation is about.
    context = SimpleNamespace(metadata={"note_document_id": page["id"]}, session_id="s1")
    text = NotesCapability().system_block(context, language="en", prompts={}).content
    assert 'opened at block a of the page: "Hello"' in text and 'selected: "Hel"' in text
    assert "opened at block" in capability.note_action_context(page["id"], session_id="s2")
    assert "opened at block" not in capability.note_action_context(page["id"], session_id="x")
    assert client.delete(f"{root}/missing").status_code == 404


def test_generated_results_file_on_their_block(storage, monkeypatch):
    import deeptutor.capabilities.notes.generation as generation

    monkeypatch.setattr(generation, "get_co_writer_storage", lambda: storage)
    target = {
        "id": "q",
        "type": "learning",
        "props": {
            "kind": "quiz",
            "prompt": "Photosynthesis",
            "markdown": "",
            "data": '{"generation": {"n": 3}}',
            "sourceUrl": "",
        },
        "children": [],
    }
    page = storage.create_document(blocks=[block(), target])
    events = [
        {"type": "content", "content": "Here are questions"},
        {
            "type": "result",
            "metadata": {
                "summary": {"results": [{"qa_pair": {"question": "Q1", "explanation": "E1"}}]}
            },
        },
    ]
    for _ in range(2):  # replaying a turn files it once
        generation.propose_generated_block(
            note_document_id=page.id,
            generation={"block_id": "q", "kind": "quiz"},
            events=events,
            response="Here are questions",
            turn_id="t1",
            explanation="Review",
        )
    from deeptutor.notes.proposals import list_proposals

    [proposal] = list_proposals(storage, page.id)
    assert proposal["operation"] == "replace" and proposal["block_id"] == "q"
    [replacement] = proposal["blocks"]
    data = json.loads(replacement["props"]["data"])
    assert replacement["id"] == "q" and replacement["props"]["prompt"] == "Photosynthesis"
    assert data["questions"][0]["question"] == "Q1" and data["generation"] == {"n": 3}
    # Plain text results still come back, as Markdown; a deleted block is skipped.
    generation.propose_generated_block(
        note_document_id=page.id,
        generation={"block_id": "zz"},
        events=[],
        response="x",
        turn_id="t2",
        explanation="",
    )
    assert len(list_proposals(storage, page.id)) == 1
