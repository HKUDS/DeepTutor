"""Doubao (豆包 / Volcengine Ark) search provider.

API: https://ark.cn-beijing.volces.com/api/v3/responses

Ark has no standalone search endpoint -- web search exists only as a built-in
``web_search`` tool on the Responses API. So a query here runs through a Doubao
model that searches, reads, and writes the answer itself, which is why this
provider reports ``supports_answer`` and skips consolidation.

Its ``sources`` knob is the real differentiator: besides the open web it can
read ByteDance-owned corpora (Toutiao news, Douyin, Moji weather) that no other
provider indexes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import requests

from ..base import BaseSearchProvider
from ..types import Citation, SearchResult, WebSearchResponse
from . import register_provider

_SOURCES = ("search_engine", "toutiao", "douyin", "moji")
# Ark pins model ids to a dated release; override via the `model` kwarg.
_DEFAULT_MODEL = "doubao-seed-1-6-251015"


@register_provider("doubao")
class DoubaoProvider(BaseSearchProvider):
    """Doubao web search provider (Volcengine Ark Responses API)."""

    description = "Doubao AI search with answers (豆包)"
    BASE_URL = "https://ark.cn-beijing.volces.com/api/v3/responses"
    API_KEY_ENV_VARS = ("ARK_API_KEY", "DOUBAO_API_KEY", "SEARCH_API_KEY")

    def search(
        self,
        query: str,
        max_results: int = 5,
        model: str = _DEFAULT_MODEL,
        sources: list[str] | None = None,
        max_keyword: int | None = None,
        timeout: int = 60,
        **kwargs: Any,
    ) -> WebSearchResponse:
        """Search via Doubao's web_search tool.

        Args:
            query: Search query.
            max_results: Passed as the tool's ``limit``.
            model: Ark model id. Ids carry a dated suffix and are retired over
                time, so this is overridable.
            sources: Corpora to search; any of ``search_engine``, ``toutiao``,
                ``douyin``, ``moji``. Defaults to ``["search_engine"]``.
            max_keyword: Cap on keywords the model expands the query into.
            timeout: Request timeout in seconds. Higher than the SERP providers
                because a model reads the pages before answering.
            **kwargs: Additional options, including ``base_url``.

        Returns:
            WebSearchResponse: Standardized search response, answer included.
        """
        selected = list(sources or ["search_engine"])
        for source in selected:
            if source not in _SOURCES:
                raise ValueError(f"Doubao source must be one of {list(_SOURCES)}, got {source!r}.")

        endpoint = str(kwargs.get("base_url") or self.BASE_URL)
        tool: dict[str, Any] = {
            "type": "web_search",
            "sources": selected,
            "limit": max(1, int(max_results)),
        }
        if max_keyword is not None:
            tool["max_keyword"] = max(1, int(max_keyword))
        payload = {"model": model, "input": query, "tools": [tool]}

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        request_kwargs: dict[str, Any] = {"headers": headers, "json": payload}
        if self.proxy:
            request_kwargs["proxies"] = {"http": self.proxy, "https": self.proxy}
        resp = requests.post(endpoint, timeout=timeout, **request_kwargs)
        if resp.status_code != 200:
            raise Exception(f"Doubao API error: {resp.status_code} - {resp.text}")

        data = resp.json()
        if data.get("error"):
            raise Exception(f"Doubao API error: {data['error']}")

        # Walk output[] -> message -> content[] -> output_text, collecting the
        # answer text and the url_citation annotations hanging off it.
        answer_parts: list[str] = []
        annotations: list[dict[str, Any]] = []
        for item in data.get("output") or []:
            if item.get("type") != "message":
                continue
            for block in item.get("content") or []:
                if block.get("type") != "output_text":
                    continue
                if block.get("text"):
                    answer_parts.append(str(block["text"]))
                for annotation in block.get("annotations") or []:
                    if annotation.get("type") == "url_citation":
                        annotations.append(annotation)

        citations: list[Citation] = []
        search_results: list[SearchResult] = []
        seen: set[str] = set()
        for annotation in annotations:
            url = str(annotation.get("url", "") or "")
            # The same source can be cited from several sentences.
            if not url or url in seen:
                continue
            seen.add(url)
            idx = len(citations) + 1
            title = str(annotation.get("title", "") or "")
            summary = str(annotation.get("summary", "") or "")
            site_name = str(annotation.get("site_name", "") or "")
            date = str(annotation.get("publish_time", "") or "")
            search_results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=summary,
                    date=date,
                    source=site_name or "Doubao",
                    content=summary,
                )
            )
            citations.append(
                Citation(
                    id=idx,
                    reference=f"[{idx}]",
                    url=url,
                    title=title,
                    snippet=summary,
                    date=date,
                    source=site_name or "Doubao",
                    content=summary,
                    icon=str(annotation.get("logo_url", "") or ""),
                    website=site_name,
                )
            )

        usage = data.get("usage") or {}
        return WebSearchResponse(
            query=query,
            answer="".join(answer_parts),
            provider="doubao",
            timestamp=datetime.now().isoformat(),
            model=str(data.get("model") or model),
            citations=citations,
            search_results=search_results,
            usage={
                "prompt_tokens": usage.get("input_tokens", 0),
                "completion_tokens": usage.get("output_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            },
            metadata={"finish_reason": data.get("status") or "stop"},
        )
