"""Download persisted book code without changing its Markdown boundaries."""

import ast

from fastapi import FastAPI
from fastapi.testclient import TestClient
from markdown_it import MarkdownIt

from deeptutor.api.routers import book as book_router
from deeptutor.book import storage as storage_module
from deeptutor.book.engine import BookEngine
from deeptutor.book.models import Block, BlockStatus, BlockType, Book, Page
from deeptutor.services.path_service import PathService
from tests.api.test_book_chapter_crud import _client, _seed


def test_markdown_download_preserves_code_and_following_prose(tmp_path, monkeypatch) -> None:
    paths = PathService(workspace_root=tmp_path / "data")
    monkeypatch.setattr(storage_module, "get_path_service", lambda: paths)
    monkeypatch.setattr(storage_module, "_storages", {})
    storage = storage_module.get_book_storage()
    engine = BookEngine(storage=storage)
    monkeypatch.setattr(book_router, "get_book_engine", lambda: engine)

    code = 'markdown = """\n```\nexample\n```\n"""\nprint(markdown)'
    ast.parse(code)  # This is a valid snippet for the code generator to accept.
    book = Book(title="Fence tutorial")
    page = Page(
        book_id=book.id,
        title="Code sample",
        blocks=[
            Block(
                type=BlockType.CODE,
                status=BlockStatus.READY,
                payload={"code": code, "language": "python"},
            ),
            Block(
                type=BlockType.TEXT, status=BlockStatus.READY, payload={"body": "After the sample."}
            ),
        ],
    )
    storage.save_book(book)
    storage.save_page(page)
    app = FastAPI()
    app.include_router(book_router.router, prefix="/api")
    with TestClient(app) as client:
        response = client.get(f"/api/books/{book.id}/export")

    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    assert response.headers["content-type"].startswith("text/markdown")
    tokens = MarkdownIt().parse(response.text)
    fences = [token for token in tokens if token.type == "fence"]
    assert len(fences) == 1
    assert fences[0].info == "python"
    assert fences[0].content == code + "\n"
    assert any(token.type == "inline" and token.content == "After the sample." for token in tokens)
    assert storage.load_page(book.id, page.id).blocks[0].payload["code"] == code


def test_markdown_download_matches_the_reordered_reader_outline(tmp_path, monkeypatch) -> None:
    client, storage = _client(tmp_path, monkeypatch)
    _seed(storage)
    # Insert a newly authored section before the older page in the same chapter.
    preview = client.post(
        "/api/books/bk/edits/preview",
        json={
            "action": "add_page",
            "chapter_id": "ch_0",
            "position": 0,
            "title": "Read this first",
            "body": "Start here.",
        },
    )
    assert preview.status_code == 200
    edit_id = preview.json()["id"]
    applied = client.post(f"/api/books/bk/edits/{edit_id}/apply", json={"expected_revision": 1})
    assert applied.status_code == 200
    reader = client.get("/api/books/bk")
    assert reader.status_code == 200
    titles = [page["title"] for page in reader.json()["pages"]]
    assert titles == ["Read this first", "Page 0", "Page 1"]

    download = client.get("/api/books/bk/export")
    assert download.status_code == 200
    tokens = MarkdownIt().parse(download.text)
    titles_in_export = [
        tokens[index + 1].content
        for index, token in enumerate(tokens)
        if token.type == "heading_open" and token.tag == "h2"
    ]
    assert titles_in_export == titles
