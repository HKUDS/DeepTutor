from tests.api.test_book_chapter_crud import _client, _seed


def test_preview_apply_undo_and_stale_revision_over_authenticated_route(tmp_path, monkeypatch):
    client, storage = _client(tmp_path, monkeypatch)
    _seed(storage)
    proposal = client.post(
        "/api/books/bk/edits/preview",
        json={"action": "add_page", "chapter_id": "ch_0", "title": "A section"},
    ).json()
    assert len(storage.list_pages("bk")) == 2
    path = "/api/books/bk/edits/" + proposal["id"]
    assert client.post(path + "/apply", json={"expected_revision": 50}).status_code == 409
    assert client.post(path + "/apply", json={"expected_revision": 1}).status_code == 200
    assert len(storage.list_pages("bk")) == 3
    assert client.post(path + "/apply", json={"expected_revision": 1}).status_code == 200
    assert client.post(path + "/undo", json={"expected_revision": 2}).status_code == 200
    assert len(storage.list_pages("bk")) == 2
    assert (
        client.post(
            "/api/books/other/edits/" + proposal["id"] + "/apply", json={"expected_revision": 1}
        ).status_code
        == 404
    )


def test_chapter_rename_updates_the_reader_and_undo_restores_it(tmp_path, monkeypatch):
    client, storage = _client(tmp_path, monkeypatch)
    _seed(storage)
    preview = "/api/books/bk/edits/preview"
    edits = "/api/books/bk/edits"
    section = client.post(
        preview,
        json={
            "action": "add_page",
            "chapter_id": "ch_0",
            "title": "An independent section",
            "body": "Section content.",
        },
    )
    assert section.status_code == 200
    section_id = section.json()["id"]
    assert client.post(f"{edits}/{section_id}/apply", json={"expected_revision": 1}).is_success
    original = client.get("/api/books/bk").json()
    original_pages = {p["id"]: p for p in original["pages"]}

    rename = client.post(
        preview, json={"action": "rename_chapter", "chapter_id": "ch_0", "title": "New chapter"}
    )
    assert rename.status_code == 200
    assert client.get("/api/books/bk").json()["pages"] == original["pages"]
    rename_id = rename.json()["id"]
    assert client.post(f"{edits}/{rename_id}/apply", json={"expected_revision": 2}).is_success

    updated = client.get("/api/books/bk").json()
    assert updated["spine"]["chapters"][0]["title"] == "New chapter"
    reader_page = client.get("/api/books/bk/pages/pg_0").json()["page"]
    assert reader_page["title"] == "New chapter"
    assert reader_page["blocks"] == original_pages["pg_0"]["blocks"]
    assert {p["id"]: p for p in updated["pages"] if p["id"] != "pg_0"} == {
        key: page for key, page in original_pages.items() if key != "pg_0"
    }

    assert client.post(f"{edits}/{rename_id}/undo", json={"expected_revision": 3}).is_success
    restored = client.get("/api/books/bk").json()
    assert restored["spine"] == original["spine"]
    assert restored["pages"] == original["pages"]
