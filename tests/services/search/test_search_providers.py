"""Provider-level tests: the resolved search config must reach the HTTP call.

`web_search` hands every provider the same `max_results` / `proxy` knobs from the
active search profile. A provider that names its parameter differently silently
drops them, which is how Serper used to ignore both (it takes `num`, and never
passed `proxies`) and Jina used to return every result it got.
"""

from __future__ import annotations

from typing import Any

import pytest

from deeptutor.services.search.providers.brave import BraveProvider
from deeptutor.services.search.providers.jina import JinaProvider
from deeptutor.services.search.providers.serper import SerperProvider
from deeptutor.services.search.providers.tavily import TavilyProvider

PROXY = "http://127.0.0.1:7890"


class _FakeResponse:
    status_code = 200
    text = ""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload


@pytest.fixture
def calls(monkeypatch):
    """Capture requests made by any provider module."""
    captured: list[dict[str, Any]] = []
    payloads: dict[str, Any] = {
        "organic": [],
        "results": [],
        "web": {"results": []},
        "data": [],
    }

    def _record(method: str):
        def _call(url: str, **kwargs: Any) -> _FakeResponse:
            captured.append({"method": method, "url": url, **kwargs})
            return _FakeResponse(payloads)

        return _call

    for module in ("serper", "tavily", "brave", "jina"):
        target = f"deeptutor.services.search.providers.{module}.requests"

        class _FakeRequests:
            get = staticmethod(_record("GET"))
            post = staticmethod(_record("POST"))

        monkeypatch.setattr(target, _FakeRequests)
    return captured


def test_serper_maps_max_results_onto_num_and_honors_proxy(calls) -> None:
    provider = SerperProvider(api_key="k", proxy=PROXY)
    provider.search("q", max_results=3, proxy=PROXY)
    assert calls[-1]["json"]["num"] == 3
    assert calls[-1]["proxies"] == {"http": PROXY, "https": PROXY}


def test_serper_keeps_its_own_num_parameter(calls) -> None:
    provider = SerperProvider(api_key="k")
    provider.search("q", num=7)
    assert calls[-1]["json"]["num"] == 7
    assert "proxies" not in calls[-1]


def test_tavily_and_brave_already_carry_the_shared_knobs(calls) -> None:
    TavilyProvider(api_key="k", proxy=PROXY).search("q", max_results=3)
    assert calls[-1]["json"]["max_results"] == 3
    assert calls[-1]["proxies"] == {"http": PROXY, "https": PROXY}

    BraveProvider(api_key="k", proxy=PROXY).search("q", max_results=3)
    assert calls[-1]["params"]["count"] == 3
    assert calls[-1]["proxies"] == {"http": PROXY, "https": PROXY}


def test_jina_truncates_results_to_max_results(monkeypatch) -> None:
    rows = [
        {"title": f"t{i}", "url": f"https://e/{i}", "description": "d", "content": "c"}
        for i in range(6)
    ]

    class _FakeRequests:
        @staticmethod
        def get(url: str, **kwargs: Any) -> _FakeResponse:
            return _FakeResponse({"data": rows})

    monkeypatch.setattr("deeptutor.services.search.providers.jina.requests", _FakeRequests)

    capped = JinaProvider(api_key="k").search("q", max_results=2)
    assert len(capped.search_results) == 2
    assert len(capped.citations) == 2
    assert [c.id for c in capped.citations] == [1, 2]

    uncapped = JinaProvider(api_key="k").search("q")
    assert len(uncapped.search_results) == len(rows)


def test_provider_metadata_comes_from_the_spec_table() -> None:
    from deeptutor.services.config import SEARCH_PROVIDERS

    for cls in (SerperProvider, TavilyProvider, BraveProvider, JinaProvider):
        spec = SEARCH_PROVIDERS[cls.name]
        assert cls.display_name == spec.label
        assert cls.requires_api_key == spec.requires_api_key
        assert cls.supports_answer == spec.supports_answer


# --------------------------------------------------------------------------
# Providers added on top of the original seven. Each names its result cap
# something different, so the shared-knob contract is where they break first.
# --------------------------------------------------------------------------

# One body that every new provider can parse to an empty result set, so a
# single fake response serves them all.
_EMPTY_BODY: dict[str, Any] = {
    "code": 200,  # bocha treats a non-2xx `code` inside a 200 as an error
    "success": True,  # firecrawl
    "data": {"webPages": {"value": []}, "web": []},  # bocha / firecrawl
    "search_result": [],  # zhipu
    "references": [],  # qianfan
    "pageItems": [],  # aliyun_iqs
    "output": [],  # doubao
}


def _limit_in_json(key: str):
    return lambda call: call["json"][key]


# (module, provider class, where the result cap lands in the request)
_NEW_PROVIDERS = [
    ("bocha", "BochaProvider", _limit_in_json("count")),
    ("zhipu", "ZhipuProvider", _limit_in_json("count")),
    ("firecrawl", "FirecrawlProvider", _limit_in_json("limit")),
    ("qianfan", "QianfanProvider", lambda c: c["json"]["resource_type_filter"][0]["top_k"]),
    ("doubao", "DoubaoProvider", lambda c: c["json"]["tools"][0]["limit"]),
    # aliyun_iqs has no count parameter at all — it caps client-side, which
    # `test_aliyun_iqs_caps_results_client_side` covers instead.
    ("aliyun_iqs", "AliyunIQSProvider", None),
]


def _provider_class(module: str, name: str):
    import importlib

    return getattr(importlib.import_module(f"deeptutor.services.search.providers.{module}"), name)


@pytest.fixture
def new_calls(monkeypatch):
    """Capture requests made by any of the newly added provider modules."""
    captured: list[dict[str, Any]] = []

    def _record(method: str):
        def _call(url: str, **kwargs: Any) -> _FakeResponse:
            captured.append({"method": method, "url": url, **kwargs})
            return _FakeResponse(_EMPTY_BODY)

        return _call

    for module, _, _ in _NEW_PROVIDERS:

        class _FakeRequests:
            get = staticmethod(_record("GET"))
            post = staticmethod(_record("POST"))

        monkeypatch.setattr(f"deeptutor.services.search.providers.{module}.requests", _FakeRequests)
    return captured


@pytest.mark.parametrize(("module", "cls_name", "read_limit"), _NEW_PROVIDERS)
def test_new_providers_carry_max_results_and_proxy(module, cls_name, read_limit, new_calls) -> None:
    provider = _provider_class(module, cls_name)(api_key="k", proxy=PROXY)
    provider.search("q", max_results=3)

    call = new_calls[-1]
    assert call["proxies"] == {"http": PROXY, "https": PROXY}
    if read_limit is not None:
        assert read_limit(call) == 3


@pytest.mark.parametrize(("module", "cls_name", "_read_limit"), _NEW_PROVIDERS)
def test_new_provider_metadata_comes_from_the_spec_table(module, cls_name, _read_limit) -> None:
    from deeptutor.services.config import SEARCH_PROVIDERS

    cls = _provider_class(module, cls_name)
    spec = SEARCH_PROVIDERS[cls.name]
    assert cls.display_name == spec.label
    assert cls.requires_api_key == spec.requires_api_key
    assert cls.supports_answer == spec.supports_answer
    # None of these can quietly become DuckDuckGo: the China-hosted ones would
    # fall back onto a network where it is unreachable.
    assert spec.soft_fallback is False


@pytest.mark.parametrize(("module", "cls_name", "_read_limit"), _NEW_PROVIDERS)
def test_new_providers_accept_a_base_url_override(module, cls_name, _read_limit, new_calls) -> None:
    """A self-hosted gateway has to be reachable without patching the class."""
    provider = _provider_class(module, cls_name)(api_key="k")
    provider.search("q", base_url="https://gateway.example/search")
    assert new_calls[-1]["url"] == "https://gateway.example/search"


def test_doubao_reads_answer_and_citations_off_annotations(monkeypatch) -> None:
    """Ark returns the answer inline; sources live in url_citation annotations."""
    body = {
        "model": "doubao-seed-1-6-251015",
        "status": "completed",
        "output": [
            {"type": "web_search_call", "id": "ws_1", "status": "completed"},
            {
                "type": "message",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": "答案。",
                        "annotations": [
                            {
                                "type": "url_citation",
                                "title": "T1",
                                "url": "https://e/1",
                                "site_name": "站点",
                                "publish_time": "2026-08-01",
                                "summary": "s1",
                            },
                            # Same source cited twice — must collapse to one.
                            {"type": "url_citation", "title": "T1", "url": "https://e/1"},
                            {"type": "url_citation", "title": "T2", "url": "https://e/2"},
                        ],
                    }
                ],
            },
        ],
        "usage": {"input_tokens": 11, "output_tokens": 22, "total_tokens": 33},
    }

    class _FakeRequests:
        @staticmethod
        def post(url: str, **kwargs: Any) -> _FakeResponse:
            return _FakeResponse(body)

    monkeypatch.setattr("deeptutor.services.search.providers.doubao.requests", _FakeRequests)

    from deeptutor.services.search.providers.doubao import DoubaoProvider

    result = DoubaoProvider(api_key="k").search("q")
    assert result.answer == "答案。"
    assert [c.url for c in result.citations] == ["https://e/1", "https://e/2"]
    assert [c.id for c in result.citations] == [1, 2]
    assert result.citations[0].website == "站点"
    assert result.citations[0].date == "2026-08-01"
    assert result.usage["total_tokens"] == 33


def test_doubao_rejects_an_unknown_source() -> None:
    from deeptutor.services.search.providers.doubao import DoubaoProvider

    with pytest.raises(ValueError, match="Doubao source"):
        DoubaoProvider(api_key="k").search("q", sources=["weibo"])


def test_qianfan_maps_its_native_citation_fields(monkeypatch) -> None:
    """Citation's web_anchor/icon/website fields came from this API's shape."""
    body = {
        "request_id": "r1",
        "references": [
            {
                "id": 1,
                "title": "T",
                "url": "https://e/1",
                "snippet": "s",
                "content": "c",
                "type": "web",
                "date": "2026-08-01",
                "web_anchor": "anchor",
                "icon": "https://e/i.png",
                "website": "站点",
            }
        ],
    }

    class _FakeRequests:
        @staticmethod
        def post(url: str, **kwargs: Any) -> _FakeResponse:
            return _FakeResponse(body)

    monkeypatch.setattr("deeptutor.services.search.providers.qianfan.requests", _FakeRequests)

    from deeptutor.services.search.providers.qianfan import QianfanProvider

    citation = QianfanProvider(api_key="k").search("q").citations[0]
    assert citation.web_anchor == "anchor"
    assert citation.website == "站点"
    assert citation.icon == "https://e/i.png"
    assert citation.type == "web"


def test_aliyun_iqs_caps_results_client_side(monkeypatch) -> None:
    """IQS always returns a page of 10; the cap has to be applied on our side."""
    body = {
        "requestId": "r1",
        "pageItems": [
            {
                "title": f"t{i}",
                "link": f"https://e/{i}",
                "snippet": "s",
                "mainText": "m",
                # Milliseconds since epoch, not a date string.
                "publishTime": 1754006400000,
                "score": 0.5,
            }
            for i in range(10)
        ],
        "searchInformation": {"total": 100},
    }

    class _FakeRequests:
        @staticmethod
        def get(url: str, **kwargs: Any) -> _FakeResponse:
            return _FakeResponse(body)

    monkeypatch.setattr("deeptutor.services.search.providers.aliyun_iqs.requests", _FakeRequests)

    from deeptutor.services.search.providers.aliyun_iqs import AliyunIQSProvider

    result = AliyunIQSProvider(api_key="k").search("q", max_results=3)
    assert len(result.search_results) == 3
    assert len(result.citations) == 3
    # The epoch stamp must not reach the model as a raw integer.
    assert result.citations[0].date.count("-") == 2


def test_bocha_surfaces_an_error_carried_inside_a_200(monkeypatch) -> None:
    class _FakeRequests:
        @staticmethod
        def post(url: str, **kwargs: Any) -> _FakeResponse:
            return _FakeResponse({"code": 403, "msg": "quota exhausted"})

    monkeypatch.setattr("deeptutor.services.search.providers.bocha.requests", _FakeRequests)

    from deeptutor.services.search.providers.bocha import BochaProvider

    with pytest.raises(Exception, match="quota exhausted"):
        BochaProvider(api_key="k").search("q")
