"""Tests for the retrieval-only Tencent WeKnora pipeline."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from deeptutor.knowledge.kb_types import CONNECTED_KB_TYPES, WEKNORA_KB_TYPE
from deeptutor.knowledge.manager import KnowledgeBaseManager
from deeptutor.services.rag.factory import get_pipeline, list_pipelines, normalize_provider_name
from deeptutor.services.rag.pipelines.weknora.client import (
    MAX_RESPONSE_BYTES,
    WeKnoraAPIError,
    WeKnoraClient,
)
from deeptutor.services.rag.pipelines.weknora.config import config_from_entry
from deeptutor.services.rag.pipelines.weknora.pipeline import WeKnoraPipeline
from deeptutor.services.rag.pipelines.weknora.probe import probe_weknora


def _transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-API-Key"] == "secret"
        if request.url.path == "/api/v1/knowledge-bases":
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": [
                        {"id": "kb-1", "name": "Research"},
                        {"id": "kb-2", "name": "Operations"},
                    ],
                },
            )
        if request.url.path == "/api/v1/knowledge-search":
            body = json.loads(request.content)
            assert body == {"query": "what is AI?", "knowledge_base_id": "kb-1"}
            assert request.url.params["resource_urls"] == "handle"
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": [
                        {
                            "id": "chunk-1",
                            "content": "Context one",
                            "knowledge_id": "knowledge-1",
                            "knowledge_title": "Guide",
                            "knowledge_filename": "guide.pdf",
                            "score": 0.9,
                        },
                        {"id": "chunk-2", "content": "Context two"},
                    ],
                },
            )
        return httpx.Response(404, json={"success": False})

    return httpx.MockTransport(handler)


def _config() -> object:
    return config_from_entry(
        {
            "server_url": "http://localhost:8080/",
            "api_key": "secret",
            "knowledge_base_id": "kb-1",
        }
    )


def test_config_requires_complete_binding() -> None:
    config = _config()
    assert config.base_url == "http://localhost:8080"
    assert config.knowledge_base_id == "kb-1"

    with pytest.raises(Exception, match="knowledge base ID"):
        config_from_entry({"server_url": "http://x", "api_key": "secret"})
    with pytest.raises(Exception, match="API key"):
        config_from_entry({"server_url": "http://x", "knowledge_base_id": "kb-1"})
    with pytest.raises(Exception, match="server URL"):
        config_from_entry(
            {
                "server_url": "ftp://example.com",
                "api_key": "secret",
                "knowledge_base_id": "kb-1",
            }
        )
    with pytest.raises(Exception, match="server URL"):
        config_from_entry(
            {
                "server_url": "http://user:password@example.com",
                "api_key": "secret",
                "knowledge_base_id": "kb-1",
            }
        )


def test_client_search_uses_official_endpoint() -> None:
    result = asyncio.run(WeKnoraClient(_config(), transport=_transport()).search("what is AI?"))
    assert [item["id"] for item in result] == ["chunk-1", "chunk-2"]


def test_client_bounds_external_response_bodies() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            headers={"content-length": str(MAX_RESPONSE_BYTES + 1)},
            content=b"{}",
        )
    )
    with pytest.raises(WeKnoraAPIError, match="4 MiB"):
        asyncio.run(WeKnoraClient(_config(), transport=transport).list_knowledge_bases())


def test_client_revalidates_saved_targets_before_retrieval() -> None:
    config = config_from_entry(
        {
            "server_url": "http://169.254.169.254",
            "api_key": "secret",
            "knowledge_base_id": "kb-1",
        }
    )
    transport = httpx.MockTransport(
        lambda _request: pytest.fail("unsafe target reached the HTTP transport")
    )
    with pytest.raises(WeKnoraAPIError, match="Unsafe WeKnora server URL"):
        asyncio.run(WeKnoraClient(config, transport=transport).list_knowledge_bases())


def test_probe_validates_visible_knowledge_base() -> None:
    probe = asyncio.run(
        probe_weknora(
            "http://localhost:8080/",
            "secret",
            "kb-1",
            client_factory=lambda config: WeKnoraClient(config, transport=_transport()),
        )
    )
    assert probe.ok is True
    assert probe.reachable is True
    assert probe.credentials_ok is True
    assert probe.knowledge_base_found is True
    assert probe.knowledge_base_name == "Research"


def test_probe_rejects_invisible_knowledge_base() -> None:
    probe = asyncio.run(
        probe_weknora(
            "http://localhost:8080",
            "secret",
            "missing",
            client_factory=lambda config: WeKnoraClient(config, transport=_transport()),
        )
    )
    assert probe.ok is False
    assert probe.knowledge_base_found is False
    assert "not visible" in (probe.error or "")


def test_probe_rejects_cloud_metadata_targets() -> None:
    probe = asyncio.run(
        probe_weknora(
            "http://169.254.169.254",
            "secret",
            "kb-1",
            client_factory=lambda _config: pytest.fail("unsafe probe opened a client"),
        )
    )
    assert probe.ok is False
    assert "Unsafe WeKnora server URL" in (probe.error or "")


def _kb_base(tmp_path: Path, entry: dict) -> str:
    (tmp_path / "kb_config.json").write_text(
        json.dumps({"knowledge_bases": {"remote": entry}}), encoding="utf-8"
    )
    return str(tmp_path)


def test_pipeline_returns_chunks_and_sources(tmp_path: Path) -> None:
    base = _kb_base(
        tmp_path,
        {
            "type": WEKNORA_KB_TYPE,
            "rag_provider": "weknora",
            "server_url": "http://localhost:8080",
            "api_key": "secret",
            "knowledge_base_id": "kb-1",
        },
    )
    pipeline = WeKnoraPipeline(
        base,
        client_factory=lambda config: WeKnoraClient(config, transport=_transport()),
    )
    result = asyncio.run(pipeline.search("what is AI?", "remote"))
    assert result["provider"] == "weknora"
    assert result["content"] == "Context one\n\n---\n\nContext two"
    assert result["sources"][0]["knowledge_title"] == "Guide"


def test_pipeline_reports_not_configured_and_retrieval_errors(tmp_path: Path) -> None:
    pipeline = WeKnoraPipeline(
        _kb_base(tmp_path, {"type": WEKNORA_KB_TYPE, "rag_provider": "weknora"}),
        client_factory=lambda config: WeKnoraClient(config, transport=_transport()),
    )
    result = asyncio.run(pipeline.search("q", "remote"))
    assert result["error_type"] == "not_configured"

    configured = WeKnoraPipeline(
        _kb_base(
            tmp_path,
            {
                "type": WEKNORA_KB_TYPE,
                "rag_provider": "weknora",
                "server_url": "http://localhost:8080",
                "api_key": "secret",
                "knowledge_base_id": "missing",
            },
        ),
        client_factory=lambda config: WeKnoraClient(
            config, transport=httpx.MockTransport(lambda request: httpx.Response(500, text="boom"))
        ),
    )
    failed = asyncio.run(configured.search("q", "remote"))
    assert failed["error_type"] == "retrieval_error"


def test_pipeline_refuses_local_indexing(tmp_path: Path) -> None:
    pipeline = WeKnoraPipeline(str(tmp_path))
    with pytest.raises(RuntimeError, match="managed in WeKnora"):
        asyncio.run(pipeline.initialize("remote", []))


def test_factory_routes_weknora() -> None:
    assert normalize_provider_name("WeKnora") == "weknora"
    assert type(get_pipeline("weknora", kb_base_dir="/tmp/kbs")).__name__ == "WeKnoraPipeline"
    assert any(item["id"] == "weknora" for item in list_pipelines())


def test_manager_pointer_hides_api_key(tmp_path: Path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path))
    entry = manager.register_weknora_kb("Remote", "http://localhost:8080/", "secret", "kb-1")
    assert WEKNORA_KB_TYPE in CONNECTED_KB_TYPES
    assert entry["server_url"] == "http://localhost:8080"
    assert not (tmp_path / "Remote").exists()

    metadata = manager.get_metadata("Remote")
    assert metadata["knowledge_base_id"] == "kb-1"
    assert "api_key" not in metadata
    assert "secret" not in str(metadata)
