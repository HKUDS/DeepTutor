from __future__ import annotations

import asyncio
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.testclient import TestClient

from deeptutor.api.routers import attachments
from deeptutor.services.storage import LocalDiskAttachmentStore


def test_uploaded_attachment_head_probes_contents_without_exposing_a_local_path(
    tmp_path, monkeypatch
):
    store = LocalDiskAttachmentStore(root=tmp_path)
    url = asyncio.run(
        store.put(
            session_id="session",
            attachment_id="upload",
            filename="学习笔记.md",
            data=b"# Uploaded notes\n",
        )
    )
    monkeypatch.setattr(attachments, "get_attachment_store", lambda: store)
    app = FastAPI()
    app.include_router(attachments.router, prefix="/files/attachments")
    client = TestClient(app)
    path = urlsplit(url).path
    metadata = client.head(path)

    assert metadata.status_code == 200
    assert metadata.headers["content-type"].startswith("text/markdown")
    assert int(metadata.headers["content-length"]) == len(b"# Uploaded notes\n")
    assert metadata.headers["content-disposition"].startswith("inline;")
    assert "x-deeptutor-local-file" not in metadata.headers
    assert client.get(path).content == b"# Uploaded notes\n"
    assert (
        client.get(path, params={"view": "browser"})
        .headers["content-type"]
        .startswith("text/plain")
    )
    assert client.head(path.replace("/upload/", "/missing/")).status_code == 404
