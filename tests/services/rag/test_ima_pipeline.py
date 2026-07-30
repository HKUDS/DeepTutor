"""Unit tests for the Tencent IMA (retrieval-only) RAG pipeline.

The engine is a thin HTTPS client over IMA's knowledge-base OpenAPI. We exercise:

* the client wire shapes (POST path, auth headers, ``{code,msg,data}`` envelope,
  cursor pagination, error-code mapping) against an injected
  ``httpx.MockTransport`` — no network,
* the connect-time probe verdict (credentials accepted / library resolves),
* the pipeline's ``search`` (reads the per-KB binding from ``kb_config.json``,
  shapes the result, and fails cleanly when unconfigured/unreachable),
* factory routing and that indexing is refused (IMA owns the index).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from deeptutor.services.rag.factory import get_pipeline, normalize_provider_name
from deeptutor.services.rag.pipelines.ima.client import (
    API_BASE_URL,
    ImaAPIError,
    ImaAuthError,
    ImaClient,
    ImaRateLimitError,
)
from deeptutor.services.rag.pipelines.ima.config import (
    ImaConfig,
    ImaNotConfiguredError,
    config_from_entry,
)
from deeptutor.services.rag.pipelines.ima.pipeline import ImaPipeline
from deeptutor.services.rag.pipelines.ima.probe import probe_knowledge_base

CONFIG = ImaConfig(client_id="cid", api_key="key", knowledge_base_id="kb-1")


def _client(handler) -> ImaClient:
    return ImaClient(CONFIG, transport=httpx.MockTransport(handler))


def _ok(data: dict) -> httpx.Response:
    return httpx.Response(200, json={"code": 0, "msg": "ok", "data": data})


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------


class TestConfigFromEntry:
    def test_full_entry_resolves(self) -> None:
        config = config_from_entry(
            {"client_id": " cid ", "api_key": "key", "knowledge_base_id": "kb-1"}
        )
        assert config == CONFIG

    @pytest.mark.parametrize(
        "entry",
        [
            {},
            {"client_id": "cid"},
            {"client_id": "cid", "api_key": "key"},
            {"api_key": "key", "knowledge_base_id": "kb-1"},
            {"client_id": "", "api_key": "key", "knowledge_base_id": "kb-1"},
        ],
    )
    def test_incomplete_entry_raises(self, entry: dict) -> None:
        with pytest.raises(ImaNotConfiguredError):
            config_from_entry(entry)

    def test_error_names_the_missing_fields(self) -> None:
        with pytest.raises(ImaNotConfiguredError) as exc:
            config_from_entry({"client_id": "cid"})
        message = str(exc.value)
        assert "API key" in message and "knowledge base ID" in message


# ---------------------------------------------------------------------------
# client
# ---------------------------------------------------------------------------


class TestClientWire:
    def test_search_posts_credentials_and_body(self) -> None:
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["headers"] = dict(request.headers)
            seen["body"] = json.loads(request.content)
            return _ok({"info_list": [], "is_end": True, "next_cursor": ""})

        asyncio.run(_client(handler).search_knowledge("q", limit=5))

        assert seen["url"] == f"{API_BASE_URL}/openapi/wiki/v1/search_knowledge"
        assert seen["headers"]["ima-openapi-clientid"] == "cid"
        assert seen["headers"]["ima-openapi-apikey"] == "key"
        # cursor is required by IMA and empty on the first page.
        assert seen["body"] == {"query": "q", "cursor": "", "knowledge_base_id": "kb-1"}

    def test_search_follows_cursor_until_end(self) -> None:
        pages = [
            {
                "info_list": [{"media_id": "m1", "title": "A", "highlight_content": "a"}],
                "is_end": False,
                "next_cursor": "c2",
            },
            {
                "info_list": [{"media_id": "m2", "title": "B", "highlight_content": "b"}],
                "is_end": True,
                "next_cursor": "",
            },
        ]
        cursors: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            cursors.append(body["cursor"])
            return _ok(pages[len(cursors) - 1])

        items = asyncio.run(_client(handler).search_knowledge("q", limit=10))

        assert cursors == ["", "c2"]
        assert [item["media_id"] for item in items] == ["m1", "m2"]

    def test_search_stops_once_limit_is_reached(self) -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return _ok(
                {
                    "info_list": [
                        {"media_id": "m1", "title": "A"},
                        {"media_id": "m2", "title": "B"},
                    ],
                    "is_end": False,
                    "next_cursor": "more",
                }
            )

        items = asyncio.run(_client(handler).search_knowledge("q", limit=2))

        assert calls == 1
        assert len(items) == 2

    def test_search_page_budget_bounds_pagination(self) -> None:
        # A server that never reports the end must not spin forever.
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return _ok({"info_list": [], "is_end": False, "next_cursor": "always-more"})

        asyncio.run(_client(handler).search_knowledge("q", limit=50))

        assert calls == 3

    def test_credential_code_maps_to_auth_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"code": 20004, "msg": "bad key"})

        with pytest.raises(ImaAuthError, match="bad key"):
            asyncio.run(_client(handler).get_knowledge_base())

    def test_rate_limit_code_maps_to_rate_limit_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"code": 110021, "msg": "slow down"})

        with pytest.raises(ImaRateLimitError):
            asyncio.run(_client(handler).get_knowledge_base())

    def test_http_429_maps_to_rate_limit_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, text="too many")

        with pytest.raises(ImaRateLimitError):
            asyncio.run(_client(handler).get_knowledge_base())

    def test_other_business_code_raises_with_message(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"code": 100001, "msg": "bad param"})

        with pytest.raises(ImaAPIError, match="bad param"):
            asyncio.run(_client(handler).get_knowledge_base())

    def test_non_json_response_raises(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="<html>nope</html>")

        with pytest.raises(ImaAPIError):
            asyncio.run(_client(handler).get_knowledge_base())

    def test_get_knowledge_base_unwraps_the_bound_id(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert json.loads(request.content) == {"ids": ["kb-1"]}
            return _ok({"infos": {"kb-1": {"id": "kb-1", "name": "My Library"}}})

        info = asyncio.run(_client(handler).get_knowledge_base())

        assert info["name"] == "My Library"

    def test_get_knowledge_base_returns_empty_for_unknown_id(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return _ok({"infos": {}})

        assert asyncio.run(_client(handler).get_knowledge_base()) == {}


# ---------------------------------------------------------------------------
# probe
# ---------------------------------------------------------------------------


class _StubClient:
    def __init__(self, *, info: dict | None = None, error: Exception | None = None) -> None:
        self._info = info or {}
        self._error = error

    async def get_knowledge_base(self) -> dict:
        if self._error is not None:
            raise self._error
        return self._info


class TestProbe:
    def test_ok_when_library_resolves(self) -> None:
        probe = asyncio.run(
            probe_knowledge_base(
                "cid",
                "key",
                "kb-1",
                client_factory=lambda _c: _StubClient(
                    info={"name": "My Library", "description": "notes"}
                ),
            )
        )
        assert probe.ok is True
        assert probe.credentials_ok is True
        assert probe.knowledge_base_name == "My Library"
        assert probe.description == "notes"
        assert probe.error is None

    def test_unknown_id_is_not_ok_but_credentials_are(self) -> None:
        probe = asyncio.run(
            probe_knowledge_base(
                "cid", "key", "kb-x", client_factory=lambda _c: _StubClient(info={})
            )
        )
        assert probe.ok is False
        assert probe.credentials_ok is True
        assert "no knowledge base matches" in (probe.error or "")

    def test_auth_error_reports_credentials(self) -> None:
        probe = asyncio.run(
            probe_knowledge_base(
                "cid",
                "bad",
                "kb-1",
                client_factory=lambda _c: _StubClient(error=ImaAuthError("rejected")),
            )
        )
        assert probe.ok is False
        assert probe.credentials_ok is False
        assert "rejected" in (probe.error or "")

    def test_transport_failure_is_reported(self) -> None:
        probe = asyncio.run(
            probe_knowledge_base(
                "cid",
                "key",
                "kb-1",
                client_factory=lambda _c: _StubClient(error=RuntimeError("offline")),
            )
        )
        assert probe.ok is False
        assert "Could not reach" in (probe.error or "")

    @pytest.mark.parametrize(
        "args",
        [("", "key", "kb-1"), ("cid", "", "kb-1"), ("cid", "key", "")],
    )
    def test_missing_input_short_circuits(self, args: tuple[str, str, str]) -> None:
        probe = asyncio.run(probe_knowledge_base(*args))
        assert probe.ok is False
        assert "is required" in (probe.error or "")


# ---------------------------------------------------------------------------
# pipeline
# ---------------------------------------------------------------------------


def _kb_config(tmp_path: Path, entry: dict) -> str:
    base = tmp_path / "kbs"
    base.mkdir(parents=True, exist_ok=True)
    (base / "kb_config.json").write_text(
        json.dumps({"knowledge_bases": {"IMA": entry}}), encoding="utf-8"
    )
    return str(base)


class _SearchStub:
    def __init__(self, items: list[dict] | None = None, error: Exception | None = None) -> None:
        self._items = items or []
        self._error = error
        self.limit: int | None = None

    async def search_knowledge(self, query: str, *, limit: int) -> list[dict]:
        self.limit = limit
        if self._error is not None:
            raise self._error
        return self._items


class TestPipelineSearch:
    def test_search_shapes_snippets_into_context_and_sources(self, tmp_path) -> None:
        base = _kb_config(
            tmp_path,
            {
                "type": "ima",
                "rag_provider": "ima",
                "client_id": "cid",
                "api_key": "key",
                "knowledge_base_id": "kb-1",
            },
        )
        stub = _SearchStub(
            [
                {"media_id": "m1", "title": "Alpha", "highlight_content": "alpha text"},
                {"media_id": "m2", "title": "Beta", "highlight_content": "beta text"},
            ]
        )
        pipeline = ImaPipeline(kb_base_dir=base, client_factory=lambda _c: stub)

        result = asyncio.run(pipeline.search("q", "IMA"))

        assert result["provider"] == "ima"
        assert "error_type" not in result
        assert [s["title"] for s in result["sources"]] == ["Alpha", "Beta"]
        assert result["sources"][0]["chunk_id"] == "m1"
        assert "[1] Alpha" in result["content"]
        assert "alpha text" in result["content"]
        assert result["answer"] == result["content"]

    def test_title_only_match_is_kept_without_a_snippet(self, tmp_path) -> None:
        base = _kb_config(
            tmp_path,
            {"client_id": "cid", "api_key": "key", "knowledge_base_id": "kb-1"},
        )
        stub = _SearchStub([{"media_id": "m1", "title": "Alpha"}])
        pipeline = ImaPipeline(kb_base_dir=base, client_factory=lambda _c: stub)

        result = asyncio.run(pipeline.search("q", "IMA"))

        assert result["sources"][0]["content"] == ""
        assert result["content"].strip() == "[1] Alpha"

    def test_unidentifiable_item_is_dropped(self, tmp_path) -> None:
        base = _kb_config(
            tmp_path,
            {"client_id": "cid", "api_key": "key", "knowledge_base_id": "kb-1"},
        )
        stub = _SearchStub([{"highlight_content": "orphan"}])
        pipeline = ImaPipeline(kb_base_dir=base, client_factory=lambda _c: stub)

        assert asyncio.run(pipeline.search("q", "IMA"))["sources"] == []

    def test_top_k_is_clamped(self, tmp_path) -> None:
        base = _kb_config(
            tmp_path,
            {"client_id": "cid", "api_key": "key", "knowledge_base_id": "kb-1"},
        )
        stub = _SearchStub()
        pipeline = ImaPipeline(kb_base_dir=base, client_factory=lambda _c: stub)

        asyncio.run(pipeline.search("q", "IMA", top_k=999))

        assert stub.limit == 50

    def test_unconfigured_kb_reports_not_configured(self, tmp_path) -> None:
        base = _kb_config(tmp_path, {"type": "ima", "rag_provider": "ima"})
        pipeline = ImaPipeline(kb_base_dir=base)

        result = asyncio.run(pipeline.search("q", "IMA"))

        assert result["error_type"] == "not_configured"
        assert result["content"] == ""
        assert result["sources"] == []

    def test_transport_failure_reports_retrieval_error(self, tmp_path) -> None:
        base = _kb_config(
            tmp_path,
            {"client_id": "cid", "api_key": "key", "knowledge_base_id": "kb-1"},
        )
        pipeline = ImaPipeline(
            kb_base_dir=base,
            client_factory=lambda _c: _SearchStub(error=RuntimeError("offline")),
        )

        result = asyncio.run(pipeline.search("q", "IMA"))

        assert result["error_type"] == "retrieval_error"
        assert "offline" in result["answer"]


class TestPipelineLifecycle:
    def test_indexing_is_refused(self, tmp_path) -> None:
        pipeline = ImaPipeline(kb_base_dir=str(tmp_path))
        with pytest.raises(RuntimeError, match="indexed by IMA"):
            asyncio.run(pipeline.initialize("IMA", ["a.pdf"]))
        with pytest.raises(RuntimeError, match="indexed by IMA"):
            asyncio.run(pipeline.add_documents("IMA", ["a.pdf"]))

    def test_delete_is_a_noop(self, tmp_path) -> None:
        pipeline = ImaPipeline(kb_base_dir=str(tmp_path))
        assert asyncio.run(pipeline.delete("IMA")) is True


class TestFactoryRouting:
    def test_provider_name_is_known(self) -> None:
        assert normalize_provider_name("ima") == "ima"

    def test_factory_builds_the_ima_pipeline(self) -> None:
        assert isinstance(get_pipeline("ima"), ImaPipeline)
