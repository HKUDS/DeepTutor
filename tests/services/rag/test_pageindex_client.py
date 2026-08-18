import asyncio

from deeptutor.services.rag.pipelines.pageindex import client as client_mod
from deeptutor.services.rag.pipelines.pageindex.client import PageIndexClient
from deeptutor.services.rag.pipelines.pageindex.config import PageIndexConfig


def test_cloud_sdk_client_is_reused_until_api_key_changes(monkeypatch) -> None:
    created: list[str] = []

    class _CloudClient:
        def __init__(self, api_key: str) -> None:
            created.append(api_key)

    monkeypatch.setattr(client_mod, "_sdk_types", lambda: (_CloudClient, object))
    client_mod._cloud_sdk_client.cache_clear()
    try:
        first = PageIndexClient.cloud(PageIndexConfig("key-a")).sdk_client
        second = PageIndexClient.cloud(PageIndexConfig("key-a")).sdk_client
        rotated = PageIndexClient.cloud(PageIndexConfig("key-b")).sdk_client
    finally:
        client_mod._cloud_sdk_client.cache_clear()

    assert first is second
    assert rotated is not first
    assert created == ["key-a", "key-b"]


def test_submit_document_uses_sdk_wait() -> None:
    calls: list[tuple[str, str | None, bool]] = []

    class _SDKClient:
        def submit_document(self, path: str, *, mode: str | None, wait: bool):
            calls.append((path, mode, wait))
            return {"doc_id": "doc-1"}

    doc_id = asyncio.run(PageIndexClient(_SDKClient()).submit_document("a.pdf", mode="flash"))

    assert doc_id == "doc-1"
    assert calls == [("a.pdf", "flash", True)]
