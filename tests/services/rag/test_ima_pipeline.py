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
    MAX_MEDIA_BYTES,
    ImaAPIError,
    ImaAuthError,
    ImaClient,
    ImaMediaContent,
    ImaRateLimitError,
)
from deeptutor.services.rag.pipelines.ima.config import (
    ImaConfig,
    ImaCredentials,
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

    def test_account_credentials_fill_in_what_the_entry_omits(self) -> None:
        config = config_from_entry(
            {"knowledge_base_id": "kb-1"},
            fallback=ImaCredentials(client_id="cid", api_key="key"),
        )
        assert config == CONFIG

    def test_entry_credentials_win_over_the_account_pair(self) -> None:
        # A KB pinned to a second IMA account must not silently retrieve
        # through the account-level credentials.
        config = config_from_entry(
            {"client_id": "other", "api_key": "other-key", "knowledge_base_id": "kb-1"},
            fallback=ImaCredentials(client_id="cid", api_key="key"),
        )
        assert config == ImaConfig(client_id="other", api_key="other-key", knowledge_base_id="kb-1")

    def test_knowledge_base_id_is_never_inherited(self) -> None:
        with pytest.raises(ImaNotConfiguredError, match="knowledge base ID"):
            config_from_entry({}, fallback=ImaCredentials(client_id="cid", api_key="key"))


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

    def test_note_media_uses_note_api(self) -> None:
        paths: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            paths.append(request.url.path)
            if request.url.path.endswith("/get_media_info"):
                assert json.loads(request.content) == {"media_id": "m-note"}
                return _ok(
                    {
                        "media_type": 11,
                        "notebook_ext_info": {"notebook_id": "note-1"},
                    }
                )
            assert json.loads(request.content) == {
                "note_id": "note-1",
                "target_content_format": 0,
            }
            return _ok({"content": " full note text "})

        media = asyncio.run(_client(handler).get_media_content("m-note"))

        assert media == ImaMediaContent(text="full note text")
        assert paths == [
            "/openapi/wiki/v1/get_media_info",
            "/openapi/note/v1/get_doc_content",
        ]

    def test_file_media_download_is_bounded_and_does_not_leak_ima_credentials(
        self,
    ) -> None:
        media_url = "https://bucket.cos.ap-guangzhou.myqcloud.com/notes.txt"

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST":
                return _ok(
                    {
                        "media_type": 1,
                        "url_info": {
                            "url": media_url,
                            "headers": {
                                "Authorization": "Bearer temporary",
                                "Cookie": "must-not-forward",
                            },
                        },
                    }
                )
            assert str(request.url) == media_url
            assert request.headers["authorization"] == "Bearer temporary"
            assert "cookie" not in request.headers
            assert "ima-openapi-clientid" not in request.headers
            assert "ima-openapi-apikey" not in request.headers
            return httpx.Response(
                200,
                content=b"full file text",
                headers={"content-type": "text/plain"},
            )

        media = asyncio.run(_client(handler).get_media_content("m-file"))

        assert media == ImaMediaContent(
            data=b"full file text",
            filename="notes.txt",
        )

    @pytest.mark.parametrize(
        "url",
        [
            "http://bucket.cos.ap-guangzhou.myqcloud.com/file.pdf",
            "https://example.com/file.pdf",
            "https://myqcloud.com.evil.test/file.pdf",
        ],
    )
    def test_file_media_rejects_urls_outside_official_cos(self, url: str) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return _ok({"media_type": 1, "url_info": {"url": url}})

        with pytest.raises(ImaAPIError):
            asyncio.run(_client(handler).get_media_content("m-file"))

    def test_file_media_rejects_content_length_over_budget(self) -> None:
        media_url = "https://bucket.cos.ap-guangzhou.myqcloud.com/file.pdf"

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST":
                return _ok({"media_type": 1, "url_info": {"url": media_url}})
            return httpx.Response(
                200,
                content=b"x",
                headers={"content-length": str(MAX_MEDIA_BYTES + 1)},
            )

        with pytest.raises(ImaAPIError, match="20 MB"):
            asyncio.run(_client(handler).get_media_content("m-file"))


class TestClientKnowledgeBaseList:
    def test_list_posts_empty_query_cursor_and_limit(self) -> None:
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["body"] = json.loads(request.content)
            return _ok({"info_list": [], "is_end": True, "next_cursor": ""})

        page = asyncio.run(_client(handler).search_knowledge_bases(query="", cursor="", limit=20))

        assert seen == {
            "url": f"{API_BASE_URL}/openapi/wiki/v1/search_knowledge_base",
            "body": {"query": "", "cursor": "", "limit": 20},
        }
        assert page == {"knowledge_bases": [], "next_cursor": "", "is_end": True}

    @pytest.mark.parametrize("limit", [0, 21])
    def test_list_rejects_limits_outside_ima_bounds(self, limit: int) -> None:
        with pytest.raises(ValueError, match="between 1 and 20"):
            asyncio.run(_client(lambda _request: _ok({})).search_knowledge_bases(limit=limit))

    def test_list_deduplicates_and_enriches_descriptions(self) -> None:
        seen_bodies: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            seen_bodies.append(body)
            if request.url.path.endswith("/search_knowledge_base"):
                return _ok(
                    {
                        "info_list": [
                            {"kb_id": "kb-1", "kb_name": "Alpha"},
                            {"kb_id": "kb-1", "kb_name": "Alpha duplicate"},
                            {"kb_id": "", "kb_name": "Missing id"},
                            {"kb_id": "kb-2", "kb_name": ""},
                            {"kb_id": "kb-3", "kb_name": "Gamma"},
                        ],
                        "is_end": False,
                        "next_cursor": "cursor-2",
                    }
                )
            assert request.url.path.endswith("/get_knowledge_base")
            return _ok(
                {
                    "infos": {
                        "kb-1": {"name": "Alpha", "description": "First notes"},
                        "kb-3": {"name": "Gamma", "description": ""},
                    }
                }
            )

        page = asyncio.run(
            _client(handler).search_knowledge_bases(query="notes", cursor="cursor-1", limit=7)
        )

        assert seen_bodies == [
            {"query": "notes", "cursor": "cursor-1", "limit": 7},
            {"ids": ["kb-1", "kb-3"]},
        ]
        assert page == {
            "knowledge_bases": [
                {"id": "kb-1", "name": "Alpha", "description": "First notes"},
                {"id": "kb-3", "name": "Gamma", "description": None},
            ],
            "next_cursor": "cursor-2",
            "is_end": False,
        }

    def test_description_enrichment_failure_keeps_search_results(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/search_knowledge_base"):
                return _ok(
                    {
                        "info_list": [{"kb_id": "kb-1", "kb_name": "Alpha"}],
                        "is_end": True,
                        "next_cursor": "",
                    }
                )
            return httpx.Response(200, text="not-json")

        page = asyncio.run(_client(handler).search_knowledge_bases())

        assert page["knowledge_bases"] == [{"id": "kb-1", "name": "Alpha", "description": None}]

    def test_list_accepts_official_id_and_name_fields(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/search_knowledge_base"):
                return _ok(
                    {
                        "info_list": [{"id": "kb-1", "name": "Official shape"}],
                        "is_end": True,
                        "next_cursor": "",
                    }
                )
            return _ok({"infos": {}})

        page = asyncio.run(_client(handler).search_knowledge_bases())

        assert page["knowledge_bases"] == [
            {"id": "kb-1", "name": "Official shape", "description": None}
        ]

    def test_get_knowledge_bases_batches_up_to_twenty_ids(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert json.loads(request.content) == {"ids": ["kb-1", "kb-2"]}
            return _ok(
                {
                    "infos": {
                        "kb-1": {"name": "Alpha"},
                        "kb-2": {"name": "Beta"},
                    }
                }
            )

        infos = asyncio.run(_client(handler).get_knowledge_bases(["kb-1", "kb-2"]))

        assert set(infos) == {"kb-1", "kb-2"}

    def test_get_knowledge_bases_rejects_more_than_twenty_ids(self) -> None:
        with pytest.raises(ValueError, match="at most 20"):
            asyncio.run(
                _client(lambda _request: _ok({})).get_knowledge_bases(
                    [f"kb-{index}" for index in range(21)]
                )
            )

    @pytest.mark.parametrize(
        ("response", "error_type"),
        [
            (httpx.Response(200, json={"code": 20004, "msg": "bad key"}), ImaAuthError),
            (
                httpx.Response(
                    401,
                    json={"code": 200002, "msg": "skill auth failed"},
                ),
                ImaAuthError,
            ),
            (
                httpx.Response(200, json={"code": 110021, "msg": "slow down"}),
                ImaRateLimitError,
            ),
        ],
    )
    def test_list_preserves_auth_and_rate_limit_error_types(
        self, response: httpx.Response, error_type: type[Exception]
    ) -> None:
        with pytest.raises(error_type):
            asyncio.run(_client(lambda _request: response).search_knowledge_bases())


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
                client_factory=lambda _c: _StubClient(error=ImaAuthError("private-key rejected")),
            )
        )
        assert probe.ok is False
        assert probe.credentials_ok is False
        assert probe.error == "IMA rejected these credentials. Check them and try again."
        assert "private" not in (probe.error or "")

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
        assert probe.error == "Could not reach Tencent IMA. Try again shortly."

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
    def __init__(
        self,
        items: list[dict] | None = None,
        error: Exception | None = None,
        media: dict[str, ImaMediaContent | None] | None = None,
    ) -> None:
        self._items = items or []
        self._error = error
        self._media = media or {}
        self.limit: int | None = None
        self.media_calls: list[str] = []

    async def search_knowledge(self, query: str, *, limit: int) -> list[dict]:
        self.limit = limit
        if self._error is not None:
            raise self._error
        return self._items

    async def get_media_content(self, media_id: str) -> ImaMediaContent | None:
        self.media_calls.append(media_id)
        return self._media.get(media_id)


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

    def test_title_only_match_loads_note_content(self, tmp_path) -> None:
        base = _kb_config(
            tmp_path,
            {"client_id": "cid", "api_key": "key", "knowledge_base_id": "kb-1"},
        )
        stub = _SearchStub(
            [{"media_id": "m1", "title": "Alpha"}],
            media={"m1": ImaMediaContent(text="quotable full text")},
        )
        pipeline = ImaPipeline(kb_base_dir=base, client_factory=lambda _c: stub)

        result = asyncio.run(pipeline.search("q", "IMA"))

        assert result["sources"][0]["content"] == "quotable full text"
        assert stub.media_calls == ["m1"]

    def test_existing_snippet_skips_full_content_fetch(self, tmp_path) -> None:
        base = _kb_config(
            tmp_path,
            {"client_id": "cid", "api_key": "key", "knowledge_base_id": "kb-1"},
        )
        stub = _SearchStub(
            [{"media_id": "m1", "title": "Alpha", "highlight_content": "snippet"}],
            media={"m1": ImaMediaContent(text="full text")},
        )
        pipeline = ImaPipeline(kb_base_dir=base, client_factory=lambda _c: stub)

        result = asyncio.run(pipeline.search("q", "IMA"))

        assert result["sources"][0]["content"] == "snippet"
        assert stub.media_calls == []

    def test_full_content_fallback_is_limited_to_three_items(self, tmp_path) -> None:
        base = _kb_config(
            tmp_path,
            {"client_id": "cid", "api_key": "key", "knowledge_base_id": "kb-1"},
        )
        items = [{"media_id": f"m{i}", "title": f"Doc {i}"} for i in range(4)]
        stub = _SearchStub(
            items,
            media={f"m{i}": ImaMediaContent(text=f"text {i}") for i in range(4)},
        )
        pipeline = ImaPipeline(kb_base_dir=base, client_factory=lambda _c: stub)

        result = asyncio.run(pipeline.search("q", "IMA"))

        assert stub.media_calls == ["m0", "m1", "m2"]
        assert [source["content"] for source in result["sources"]] == [
            "text 0",
            "text 1",
            "text 2",
            "",
        ]

    def test_downloaded_text_file_is_extracted(self, tmp_path) -> None:
        base = _kb_config(
            tmp_path,
            {"client_id": "cid", "api_key": "key", "knowledge_base_id": "kb-1"},
        )
        stub = _SearchStub(
            [{"media_id": "m1", "title": "Alpha.txt"}],
            media={"m1": ImaMediaContent(data=b"full file text", filename="download")},
        )
        pipeline = ImaPipeline(kb_base_dir=base, client_factory=lambda _c: stub)

        result = asyncio.run(pipeline.search("q", "IMA"))

        assert result["sources"][0]["content"] == "full file text"

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

    def test_kb_without_credentials_uses_the_account_pair(self, tmp_path, monkeypatch) -> None:
        import deeptutor.services.config as config_module
        from deeptutor.services.config.runtime_settings import RuntimeSettingsService

        service = RuntimeSettingsService(tmp_path / "settings", process_env={})
        service.save_ima({"client_id": "cid", "api_key": "key"})
        monkeypatch.setattr(config_module, "get_runtime_settings_service", lambda: service)

        base = _kb_config(tmp_path, {"type": "ima", "knowledge_base_id": "kb-1"})
        seen: list[ImaConfig] = []

        def factory(config: ImaConfig):
            seen.append(config)
            return _SearchStub([{"media_id": "m1", "title": "Alpha", "highlight_content": "a"}])

        pipeline = ImaPipeline(kb_base_dir=base, client_factory=factory)

        result = asyncio.run(pipeline.search("q", "IMA"))

        assert seen == [CONFIG]
        assert [source["title"] for source in result["sources"]] == ["Alpha"]

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
