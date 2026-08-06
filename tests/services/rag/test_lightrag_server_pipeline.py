"""Unit tests for the LightRAG Server (retrieval-only) RAG pipeline.

The engine is a thin HTTP client over an external LightRAG server. We exercise:

* the client wire shapes (``/query`` only_need_context, references→sources) against
  an injected ``httpx.MockTransport`` — no network,
* the connect-time probe verdict (reachable / auth-required / key accepted),
* the pipeline's ``search`` (reads the per-KB endpoint from ``kb_config.json``,
  shapes the result, and fails cleanly when unconfigured/unreachable),
* factory routing and that indexing is refused (the server owns the index).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx

from deeptutor.services.rag.factory import get_pipeline, normalize_provider_name
from deeptutor.services.rag.pipelines.lightrag_server.client import LightRagServerClient
from deeptutor.services.rag.pipelines.lightrag_server.config import (
    DEFAULT_MODE,
    LightRagServerConfig,
    LightRagServerNotConfiguredError,
    config_from_entry,
)
from deeptutor.services.rag.pipelines.lightrag_server.pipeline import LightRagServerPipeline
from deeptutor.services.rag.pipelines.lightrag_server.probe import probe_server


def _transport(*, auth_configured: bool = True, valid_key: str | None = "secret"):
    """A MockTransport emulating a LightRAG server's relevant endpoints."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/query":
            body = json.loads(request.content)
            assert body["only_need_context"] is True
            return httpx.Response(
                200,
                json={
                    "response": f"CONTEXT[{body['mode']}]",
                    "references": [
                        {"reference_id": "1", "file_path": "/docs/a.pdf"},
                        {"reference_id": "2", "file_path": "/docs/b.pdf"},
                        {"reference_id": "", "file_path": ""},  # dropped
                    ],
                },
            )
        if path == "/auth-status":
            return httpx.Response(
                200,
                json={
                    "auth_configured": auth_configured,
                    "core_version": "1.2.3",
                    "api_version": "0150",
                },
            )
        if path == "/documents/pipeline_status":
            key = request.headers.get("X-API-Key")
            ok = valid_key is None or key == valid_key
            return httpx.Response(200 if ok else 403, json={})
        return httpx.Response(404, json={})

    return httpx.MockTransport(handler)


def _client_factory(transport):
    return lambda config: LightRagServerClient(config, transport=transport)


# ----- config ------------------------------------------------------------


def test_config_from_entry_requires_server_url() -> None:
    cfg = config_from_entry({"server_url": "http://x:9621/", "api_key": "k"})
    assert cfg.base_url == "http://x:9621"  # trailing slash trimmed
    assert cfg.api_key == "k"

    try:
        config_from_entry({"api_key": "k"})
    except LightRagServerNotConfiguredError:
        pass
    else:  # pragma: no cover - explicit failure
        raise AssertionError("expected LightRagServerNotConfiguredError")


# ----- client ------------------------------------------------------------


def test_client_query_context_maps_references_to_sources() -> None:
    client = LightRagServerClient(
        LightRagServerConfig("http://x", "secret"), transport=_transport()
    )
    result = asyncio.run(client.query_context("what is AI?", "mix"))
    assert result["content"] == "CONTEXT[mix]"
    assert result["sources"] == [
        {"id": "1", "file_path": "/docs/a.pdf"},
        {"id": "2", "file_path": "/docs/b.pdf"},
    ]


def test_client_verify_key_true_and_false() -> None:
    good = LightRagServerClient(LightRagServerConfig("http://x", "secret"), transport=_transport())
    bad = LightRagServerClient(LightRagServerConfig("http://x", "wrong"), transport=_transport())
    assert asyncio.run(good.verify_key()) is True
    assert asyncio.run(bad.verify_key()) is False


# ----- probe -------------------------------------------------------------


def test_probe_ok_when_reachable_and_key_valid() -> None:
    probe = asyncio.run(
        probe_server("http://x:9621/", "secret", client_factory=_client_factory(_transport()))
    )
    assert probe.ok is True
    assert probe.reachable is True
    assert probe.auth_required is True
    assert probe.auth_ok is True
    assert probe.core_version == "1.2.3"
    assert probe.base_url == "http://x:9621"


def test_probe_rejects_bad_key() -> None:
    probe = asyncio.run(
        probe_server("http://x", "wrong", client_factory=_client_factory(_transport()))
    )
    assert probe.ok is False
    assert probe.auth_ok is False
    assert probe.error


def test_probe_open_server_needs_no_key() -> None:
    probe = asyncio.run(
        probe_server(
            "http://x",
            "",
            client_factory=_client_factory(_transport(auth_configured=False)),
        )
    )
    assert probe.ok is True
    assert probe.auth_required is False


def test_probe_rejects_non_http_url() -> None:
    probe = asyncio.run(probe_server("ftp://x"))
    assert probe.ok is False
    assert probe.reachable is False
    assert probe.error


def test_probe_unreachable_server_reports_error() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    probe = asyncio.run(
        probe_server("http://x", "", client_factory=_client_factory(httpx.MockTransport(boom)))
    )
    assert probe.ok is False
    assert "Could not reach" in (probe.error or "")


# ----- pipeline ----------------------------------------------------------


def _kb_base(tmp_path: Path, entry: dict) -> str:
    (tmp_path / "kb_config.json").write_text(
        json.dumps({"knowledge_bases": {"remote": entry}}), encoding="utf-8"
    )
    return str(tmp_path)


def test_search_returns_grounded_context(tmp_path: Path) -> None:
    base = _kb_base(
        tmp_path,
        {
            "type": "lightrag_server",
            "rag_provider": "lightrag-server",
            "server_url": "http://x",
            "api_key": "secret",
            "search_mode": "hybrid",
        },
    )
    pipe = LightRagServerPipeline(kb_base_dir=base, client_factory=_client_factory(_transport()))
    res = asyncio.run(pipe.search("q", "remote"))
    assert res["provider"] == "lightrag-server"
    assert res["mode"] == "hybrid"  # per-KB search_mode wins
    assert res["content"] == "CONTEXT[hybrid]"
    assert res["answer"] == res["content"]
    assert res["sources"][0]["file_path"] == "/docs/a.pdf"


def test_search_defaults_mode_when_unset(tmp_path: Path) -> None:
    base = _kb_base(
        tmp_path,
        {
            "type": "lightrag_server",
            "rag_provider": "lightrag-server",
            "server_url": "http://x",
            "api_key": "secret",
        },
    )
    pipe = LightRagServerPipeline(kb_base_dir=base, client_factory=_client_factory(_transport()))
    res = asyncio.run(pipe.search("q", "remote"))
    assert res["mode"] == DEFAULT_MODE


def test_search_not_configured_when_no_url(tmp_path: Path) -> None:
    base = _kb_base(tmp_path, {"type": "lightrag_server", "rag_provider": "lightrag-server"})
    pipe = LightRagServerPipeline(kb_base_dir=base, client_factory=_client_factory(_transport()))
    res = asyncio.run(pipe.search("q", "remote"))
    assert res["error_type"] == "not_configured"
    assert res["content"] == ""


def test_search_surfaces_retrieval_error(tmp_path: Path) -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    base = _kb_base(
        tmp_path,
        {
            "type": "lightrag_server",
            "rag_provider": "lightrag-server",
            "server_url": "http://x",
        },
    )
    pipe = LightRagServerPipeline(
        kb_base_dir=base, client_factory=_client_factory(httpx.MockTransport(boom))
    )
    res = asyncio.run(pipe.search("q", "remote"))
    assert res["error_type"] == "retrieval_error"


def test_initialize_and_add_documents_are_refused(tmp_path: Path) -> None:
    pipe = LightRagServerPipeline(kb_base_dir=str(tmp_path))
    for coro in (pipe.initialize("kb", []), pipe.add_documents("kb", [])):
        try:
            asyncio.run(coro)
        except RuntimeError as exc:
            assert "external server" in str(exc)
        else:  # pragma: no cover - explicit failure
            raise AssertionError("expected RuntimeError")


def test_delete_is_noop_true(tmp_path: Path) -> None:
    pipe = LightRagServerPipeline(kb_base_dir=str(tmp_path))
    assert asyncio.run(pipe.delete("anything")) is True


# ----- factory routing ---------------------------------------------------


def test_factory_dispatches_lightrag_server(tmp_path: Path) -> None:
    assert normalize_provider_name("lightrag-server") == "lightrag-server"
    pipe = get_pipeline("lightrag-server", kb_base_dir=str(tmp_path))
    assert type(pipe).__name__ == "LightRagServerPipeline"
