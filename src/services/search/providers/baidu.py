# -*- coding: utf-8 -*-
"""
Baidu AI Search Provider

API: https://qianfan.baidubce.com/v2/ai_search/chat/completions

Features:
- AI-powered search with ERNIE models
- Deep search mode for comprehensive results
- Corner markers for reference citations
- Follow-up query suggestions
- Recency filtering
"""

from datetime import datetime
from typing import Any

import requests

from ..base import BaseSearchProvider
from ..types import Citation, SearchResult, WebSearchResponse
from . import register_provider


@register_provider("baidu")
class BaiduProvider(BaseSearchProvider):
    """Baidu AI Search provider"""

    display_name = "Baidu AI"
    description = "百度AI搜索 with ERNIE models"
    supports_answer = True
    BASE_URL = "https://qianfan.baidubce.com/v2/ai_search/chat/completions"

    def search(
        self,
        query: str,
        model: str = "ernie-4.5-turbo-32k",
        search_source: str = "baidu_search_v2",
        enable_deep_search: bool = False,
        enable_corner_markers: bool = True,
        enable_followup_queries: bool = False,
        temperature: float = 0.11,
        top_p: float = 0.55,
        search_mode: str = "auto",
        search_recency_filter: str | None = None,
        instruction: str = "",
        timeout: int = 120,
        **kwargs: Any,
    ) -> WebSearchResponse:
        """
        Perform intelligent search using Baidu AI Search API.

        Args:
            query: Search query.
            model: Model to use for generation (default: ernie-4.5-turbo-32k).
            search_source: Search engine version (baidu_search_v1 or baidu_search_v2).
            enable_deep_search: Enable deep search for more comprehensive results.
            enable_corner_markers: Enable corner markers for reference citations.
            enable_followup_queries: Enable follow-up query suggestions.
            temperature: Model sampling temperature (0, 1].
            top_p: Model sampling top_p (0, 1].
            search_mode: Search mode (auto, required, disabled).
            search_recency_filter: Filter by recency (week, month, semiyear, year).
            instruction: System instruction for response style.
            timeout: Request timeout in seconds.
            **kwargs: Additional options.

        Returns:
            WebSearchResponse: Standardized search response.
        """
        self.logger.debug(f"Calling Baidu API with model={model}, deep_search={enable_deep_search}")
        headers = {
            "Content-Type": "application/json",
            "Authorization": (
                f"Bearer {self.api_key}" if not self.api_key.startswith("Bearer ") else self.api_key
            ),
        }

        payload = {
            "messages": [{"role": "user", "content": query}],
            "model": model,
            "search_source": search_source,
            "stream": False,
            "enable_deep_search": enable_deep_search,
            "enable_corner_markers": enable_corner_markers,
            "enable_followup_queries": enable_followup_queries,
            "temperature": temperature,
            "top_p": top_p,
            "search_mode": search_mode,
        }

        if search_recency_filter:
            payload["search_recency_filter"] = search_recency_filter

        if instruction:
            payload["instruction"] = instruction

        response = requests.post(self.BASE_URL, headers=headers, json=payload, timeout=timeout)

        if response.status_code != 200:
            try:
                error_data = response.json() if response.text else {}
            except Exception:
                error_data = {}
            raise Exception(
                f"Baidu AI Search API error: {response.status_code} - "
                f"{error_data.get('message', response.text)}"
            )

        try:
            data = response.json()
        except Exception as e:
            raise Exception(f"Failed to parse Baidu API response: {e}")

        # Extract answer from response
        answer = ""
        finish_reason = ""
        if data.get("choices"):
            choice = data["choices"][0]
            if choice.get("message"):
                answer = choice["message"].get("content", "")
            finish_reason = choice.get("finish_reason", "")

        # Extract usage information
        usage_info: dict[str, Any] = {}
        if data.get("usage"):
            usage = data["usage"]
            usage_info = {
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            }

        # Extract references/citations
        citations: list[Citation] = []
        search_results: list[SearchResult] = []

        if data.get("references"):
            for i, ref in enumerate(data["references"], 1):
                citations.append(
                    Citation(
                        id=ref.get("id", i),
                        reference=f"[{ref.get('id', i)}]",
                        url=ref.get("url", ""),
                        title=ref.get("title", ""),
                        snippet=ref.get("content", ""),
                        date=ref.get("date", ""),
                        source=ref.get("web_anchor", ""),
                        type=ref.get("type", "web"),
                        icon=ref.get("icon", ""),
                        website=ref.get("website", ""),
                        web_anchor=ref.get("web_anchor", ""),
                    )
                )

                search_results.append(
                    SearchResult(
                        title=ref.get("title", ""),
                        url=ref.get("url", ""),
                        snippet=ref.get("content", ""),
                        date=ref.get("date", ""),
                        source=ref.get("web_anchor", ""),
                    )
                )

        # Build metadata
        metadata: dict[str, Any] = {
            "finish_reason": finish_reason,
            "is_safe": data.get("is_safe", True),
            "request_id": data.get("request_id", ""),
        }

        # Add follow-up queries if available
        if data.get("followup_queries"):
            metadata["followup_queries"] = data["followup_queries"]

        response_obj = WebSearchResponse(
            query=query,
            answer=answer,
            provider="baidu",
            timestamp=datetime.now().isoformat(),
            model=model,
            citations=citations,
            search_results=search_results,
            usage=usage_info,
            metadata=metadata,
        )

        return response_obj
