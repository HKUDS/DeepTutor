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


# --------------------------------------------------------------------------
# Serply: one key, three Google verticals (web / news / scholar). It is a GET
# API, so the cap lands in `params`, and the news feed ignores `num` server-side.
# --------------------------------------------------------------------------

_SERPLY_BODIES: dict[str, dict[str, Any]] = {
    "search": {
        "results": [
            {
                "title": "Attention Is All You Need - arXiv",
                "link": "https://arxiv.org/abs/1706.03762",
                "description": "The dominant sequence transduction models...",
                "metadata": {"display_url": "arxiv.org"},
            }
        ],
        "related_searches": [{"query": "transformer paper"}],
    },
    "news": {
        "feed": {
            "entries": [
                {
                    "title": f"Story {i}",
                    "link": f"https://news.example/{i}",
                    "summary": "<a href='x'>Genuine</a> attention &amp; chatbots",
                    "published": "Mon, 25 Aug 2026 09:00:00 GMT",
                    "source": "Example Times",
                }
                for i in range(10)
            ]
        }
    },
    "scholar": {
        "articles": [
            {
                "id": "W2626778328",
                "title": "Attention Is All You Need",
                "link": "https://doi.org/10.65215/2q58a426",
                "description": "We propose a new simple network architecture...",
                "author": {"names": "A Vaswani, N Shazeer - 2017"},
                "extras": {"citations": {"count": 120000}},
                "doc": {"link": "https://example.org/attention.pdf", "type": "PDF"},
            }
        ]
    },
}


@pytest.fixture
def serply_calls(monkeypatch):
    """Capture Serply GETs and answer each with the fixture body for its mode."""
    captured: list[dict[str, Any]] = []

    def _get(url: str, **kwargs: Any) -> _FakeResponse:
        captured.append({"method": "GET", "url": url, **kwargs})
        mode = url.rsplit("/", 2)[-2]
        return _FakeResponse(_SERPLY_BODIES[mode])

    class _FakeRequests:
        get = staticmethod(_get)

    monkeypatch.setattr("deeptutor.services.search.providers.serply.requests", _FakeRequests)
    return captured


def test_serply_carries_max_results_proxy_and_base_url_root(serply_calls) -> None:
    from deeptutor.services.search.providers.serply import SerplyProvider

    provider = SerplyProvider(api_key="k", proxy=PROXY)
    provider.search("attention & focus", max_results=3, base_url="https://gateway.example/v1/")

    call = serply_calls[-1]
    assert call["url"] == ("https://gateway.example/v1/search/q=attention+%26+focus&num=3")
    assert "params" not in call
    assert call["headers"]["X-Api-Key"] == "k"
    assert call["proxies"] == {"http": PROXY, "https": PROXY}


def test_serply_metadata_comes_from_the_spec_table() -> None:
    from deeptutor.services.config import SEARCH_PROVIDERS
    from deeptutor.services.search.providers import list_providers
    from deeptutor.services.search.providers.serply import SerplyProvider

    spec = SEARCH_PROVIDERS["serply"]
    assert "serply" in list_providers()
    assert SerplyProvider.display_name == spec.label
    assert SerplyProvider.requires_api_key is True
    assert SerplyProvider.supports_answer is False
    # Paid provider: never quietly turn a billed key into DuckDuckGo.
    assert spec.soft_fallback is False


def test_serply_web_rows_map_onto_search_results(serply_calls) -> None:
    from deeptutor.services.search.providers.serply import SerplyProvider

    response = SerplyProvider(api_key="k").search("attention is all you need")

    assert response.provider == "serply"
    assert response.answer == ""
    (row,) = response.search_results
    assert row.url == "https://arxiv.org/abs/1706.03762"
    assert row.source == "arxiv.org"
    assert response.citations[0].reference == "[1]"
    assert response.metadata["relatedSearches"] == [{"query": "transformer paper"}]


def test_serply_news_trims_client_side_and_strips_html(serply_calls) -> None:
    from deeptutor.services.search.providers.serply import SerplyProvider

    response = SerplyProvider(api_key="k").search("chatbots", mode="news", max_results=4)

    assert "/news/q=chatbots&num=4" in serply_calls[-1]["url"]
    assert len(response.search_results) == 4
    assert response.search_results[0].snippet == "Genuine attention & chatbots"
    assert response.search_results[0].source == "Example Times"
    assert response.search_results[0].date.startswith("Mon, 25 Aug 2026")


def test_serply_scholar_rows_render_through_the_academic_template(serply_calls) -> None:
    from deeptutor.services.search.consolidation import AnswerConsolidator
    from deeptutor.services.search.providers.serply import SerplyProvider

    response = SerplyProvider(api_key="k").search("attention", mode="scholar")

    assert response.provider == "serply_scholar"
    (row,) = response.search_results
    assert row.attributes == {
        "publicationInfo": "A Vaswani, N Shazeer - 2017",
        "citedBy": 120000,
        "pdfUrl": "https://example.org/attention.pdf",
        "paperId": "W2626778328",
    }
    rendered = AnswerConsolidator().consolidate(response).answer
    assert "Cited by: 120000" in rendered
    assert "[PDF](https://example.org/attention.pdf)" in rendered


def test_serply_rejects_an_unknown_mode() -> None:
    from deeptutor.services.search.providers.serply import SerplyProvider

    with pytest.raises(ValueError, match="mode"):
        SerplyProvider(api_key="k").search("q", mode="images")


# --------------------------------------------------------------------------
# You.com: authenticated Search API.
# --------------------------------------------------------------------------

_YOUCOM_BODY: dict[str, Any] = {
    "results": {
        "web": [
            {
                "url": "https://example.com/guide",
                "title": "Example Guide",
                "description": "Fallback description",
                "snippets": ["First passage.", "Second passage."],
                "page_age": "2026-10-01T12:00:00Z",
            },
            {
                "url": "https://example.org/second",
                "title": "Second Guide",
                "description": "Description only",
            },
        ]
    },
    "metadata": {"search_uuid": "uuid-123", "latency": 0.42},
}


@pytest.fixture
def youcom_calls(monkeypatch):
    captured: list[dict[str, Any]] = []

    def _get(url: str, **kwargs: Any) -> _FakeResponse:
        captured.append({"method": "GET", "url": url, **kwargs})
        return _FakeResponse(_YOUCOM_BODY)

    class _FakeRequests:
        get = staticmethod(_get)

    monkeypatch.setattr("deeptutor.services.search.providers.youcom.requests", _FakeRequests)
    return captured


def test_youcom_rejects_missing_key_before_network(youcom_calls, monkeypatch) -> None:
    from deeptutor.services.search.providers.youcom import YouComProvider

    monkeypatch.setattr(YouComProvider, "_get_api_key", lambda self: "")
    with pytest.raises(ValueError, match="requires an API key"):
        YouComProvider(proxy=PROXY).search("attention")
    assert youcom_calls == []


def test_youcom_keyed_request_uses_search_api_endpoint_and_header(youcom_calls) -> None:
    from deeptutor.services.search.providers.youcom import YouComProvider

    YouComProvider(api_key="k").search("attention", max_results=3)

    call = youcom_calls[-1]
    assert call["url"] == "https://ydc-index.io/v1/search"
    assert call["params"]["count"] == 3
    assert call["headers"]["X-API-Key"] == "k"


def test_youcom_maps_rows_snippets_and_metadata(youcom_calls) -> None:
    from deeptutor.services.search.providers.youcom import YouComProvider

    response = YouComProvider(api_key="k").search("attention", max_results=1)

    assert response.provider == "you"
    assert response.answer == ""
    assert response.model == "you-web-search"
    (row,) = response.search_results
    assert row.title == "Example Guide"
    assert row.url == "https://example.com/guide"
    assert row.snippet == "First passage.\nSecond passage."
    assert row.source == "example.com"
    assert row.date == "2026-10-01T12:00:00Z"
    assert response.citations[0].reference == "[1]"
    assert response.metadata == {
        "finish_reason": "stop",
        "search_uuid": "uuid-123",
        "latency": 0.42,
    }


def test_youcom_maps_description_when_snippets_are_absent(youcom_calls) -> None:
    from deeptutor.services.search.providers.youcom import YouComProvider

    response = YouComProvider(api_key="k").search("attention", max_results=2)

    assert response.search_results[1].snippet == "Description only"
    assert response.search_results[1].source == "example.org"


def test_youcom_metadata_comes_from_the_spec_table() -> None:
    from deeptutor.services.config import SEARCH_PROVIDERS
    from deeptutor.services.search.providers import list_providers
    from deeptutor.services.search.providers.youcom import YouComProvider

    spec = SEARCH_PROVIDERS["you"]
    assert "you" in list_providers()
    assert YouComProvider.display_name == spec.label
    assert YouComProvider.requires_api_key is True
    assert YouComProvider.supports_answer is False
    assert spec.soft_fallback is True


def test_youcom_surfaces_http_errors(monkeypatch) -> None:
    class _ErrorResponse:
        status_code = 429
        text = "rate limit exceeded"

        def json(self) -> dict[str, Any]:
            return {}

    class _FakeRequests:
        @staticmethod
        def get(url: str, **kwargs: Any) -> _ErrorResponse:
            return _ErrorResponse()

    monkeypatch.setattr("deeptutor.services.search.providers.youcom.requests", _FakeRequests)

    from deeptutor.services.search.providers.youcom import YouComProvider

    with pytest.raises(Exception, match="429 - rate limit exceeded"):
        YouComProvider(api_key="k").search("q")


def test_perplexity_client_sends_integration_header() -> None:
    from perplexity._models import FinalRequestOptions

    from deeptutor.services.search.providers.perplexity import PerplexityProvider

    client = PerplexityProvider(api_key="test").client
    request = client._build_request(
        FinalRequestOptions.construct(method="post", url="/chat/completions", json_data={})
    )
    assert request.url.host == "api.perplexity.ai"
    assert request.headers["X-Pplx-Integration"] == "deeptutor"


# --------------------------------------------------------------------------
# google-browser-scraper: a self-hosted `serve` endpoint answering SerpApi-shaped
# JSON. A blocked page arrives as HTTP 200 with an error status, and has to
# raise so web_search can fall through to the next provider.
# --------------------------------------------------------------------------


def _gbs_page(status: str = "Success", verdict: str = "results", rows=None) -> dict[str, Any]:
    return {
        "search_metadata": {"status": status, "page_verdict": verdict},
        "search_parameters": {"engine": "google", "q": "q", "page": 1},
        "organic_results": rows or [],
    }


@pytest.fixture
def gbs(monkeypatch):
    """Capture GETs to the scraper and answer with whatever `gbs.body` holds."""

    class _State:
        body: Any = _gbs_page()
        status_code = 200
        calls: list[dict[str, Any]] = []

    state = _State()

    def _get(url: str, **kwargs: Any) -> _FakeResponse:
        state.calls.append({"url": url, **kwargs})
        response = _FakeResponse(state.body)
        response.status_code = state.status_code
        return response

    class _FakeRequests:
        get = staticmethod(_get)
        HTTPError = __import__("requests").HTTPError
        exceptions = __import__("requests").exceptions

    monkeypatch.setattr(
        "deeptutor.services.search.providers.google_browser_scraper.requests", _FakeRequests
    )
    return state


def test_gbs_queries_search_json_with_key_proxy_and_cap(gbs) -> None:
    from deeptutor.services.search.providers.google_browser_scraper import (
        GoogleBrowserScraperProvider,
    )

    gbs.body = _gbs_page(
        rows=[
            {"position": i, "title": f"T{i}", "link": f"https://e.example/{i}", "snippet": "s"}
            for i in range(1, 9)
        ]
    )
    provider = GoogleBrowserScraperProvider(api_key="k", proxy=PROXY)
    response = provider.search("q", base_url="http://127.0.0.1:8000/", max_results=3)

    call = gbs.calls[-1]
    assert call["url"] == "http://127.0.0.1:8000/search.json"
    assert call["params"] == {"q": "q"}
    assert call["headers"]["Authorization"] == "Bearer k"
    assert call["proxies"] == {"http": PROXY, "https": PROXY}
    assert call["timeout"] >= 60
    assert [r.url for r in response.search_results] == [
        "https://e.example/1",
        "https://e.example/2",
        "https://e.example/3",
    ]
    assert [c.reference for c in response.citations] == ["[1]", "[2]", "[3]"]
    assert response.provider == "google_browser_scraper"


def test_gbs_sends_no_key_when_none_is_set(gbs) -> None:
    from deeptutor.services.search.providers.google_browser_scraper import (
        GoogleBrowserScraperProvider,
    )

    GoogleBrowserScraperProvider(api_key="").search("q", base_url="localhost:8000")
    call = gbs.calls[-1]
    assert call["url"] == "http://localhost:8000/search.json"
    assert "Authorization" not in call["headers"]
    assert "proxies" not in call


def test_gbs_skips_rows_without_a_web_link(gbs) -> None:
    from deeptutor.services.search.providers.google_browser_scraper import (
        GoogleBrowserScraperProvider,
    )

    gbs.body = _gbs_page(
        rows=[
            {
                "title": "Unresolved",
                "link": None,
                "redirect_link": "https://www.google.com/url?q=x",
            },
            {"title": "Kept", "link": "https://kept.example", "snippet": "s", "date": "2 days ago"},
            {"title": "Local", "link": "file:///etc/passwd"},
        ]
    )
    response = GoogleBrowserScraperProvider(api_key="").search("q", base_url="http://h:8000")
    assert [(r.title, r.url, r.date) for r in response.search_results] == [
        ("Kept", "https://kept.example", "2 days ago")
    ]
    assert response.citations[0].id == 1


def test_gbs_reports_a_blocked_page_instead_of_no_results(gbs) -> None:
    from deeptutor.services.search.providers.google_browser_scraper import (
        GoogleBrowserScraperError,
        GoogleBrowserScraperProvider,
    )

    gbs.body = _gbs_page(status="Error", verdict="captcha")
    with pytest.raises(GoogleBrowserScraperError, match="captcha"):
        GoogleBrowserScraperProvider(api_key="").search("q", base_url="http://h:8000")


def test_gbs_http_errors_keep_the_status_without_the_body(gbs) -> None:
    import requests

    from deeptutor.services.search.providers.google_browser_scraper import (
        GoogleBrowserScraperProvider,
    )

    gbs.status_code = 401
    gbs.body = {"error": "missing or wrong api_key"}
    with pytest.raises(requests.HTTPError) as excinfo:
        GoogleBrowserScraperProvider(api_key="k").search("q", base_url="http://h:8000")
    assert "401" in str(excinfo.value)
    assert "missing or wrong" not in str(excinfo.value)


def test_gbs_requires_a_valid_base_url() -> None:
    import requests

    from deeptutor.services.search.providers.google_browser_scraper import (
        GoogleBrowserScraperProvider,
    )

    provider = GoogleBrowserScraperProvider(api_key="")
    with pytest.raises(ValueError, match="base_url"):
        provider.search("q")
    with pytest.raises(requests.exceptions.InvalidURL):
        provider.search("q", base_url="ftp://h:8000")


def test_gbs_metadata_comes_from_the_spec_table() -> None:
    from deeptutor.services.config import SEARCH_PROVIDERS, search_missing_credential
    from deeptutor.services.search.providers import list_providers
    from deeptutor.services.search.providers.google_browser_scraper import (
        GoogleBrowserScraperProvider,
    )

    spec = SEARCH_PROVIDERS["google_browser_scraper"]
    assert "google_browser_scraper" in list_providers()
    assert GoogleBrowserScraperProvider.display_name == spec.label
    assert GoogleBrowserScraperProvider.requires_api_key is False
    assert GoogleBrowserScraperProvider.supports_answer is False
    assert search_missing_credential("google_browser_scraper", "", "") == "base_url"
