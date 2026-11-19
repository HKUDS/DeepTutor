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
