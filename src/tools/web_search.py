#!/usr/bin/env python
"""
Web Search Tool - Network search using Perplexity API or Baidu AI Search API
"""

from datetime import datetime
from enum import Enum
import json
import os

import requests

try:
    from perplexity import Perplexity

    PERPLEXITY_AVAILABLE = True
except ImportError:
    PERPLEXITY_AVAILABLE = False
    Perplexity = None


class SearchProvider(str, Enum):
    """Supported search providers"""

    PERPLEXITY = "perplexity"
    BAIDU = "baidu"
    VOLCENGINE = "volcengine"


class VolcengineSearch:
    """Volcano Engine Integrated Information Search client"""

    SEARCH_ENDPOINT = "https://open.feedcoopapi.com/search_api/web_search"

    def __init__(self, api_key: str):
        """
        Initialize Volcano Engine Search client

        Args:
            api_key: Volcano Engine API Key
        """
        self.api_key = api_key
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

    def search(
        self,
        query: str,
        page_size: int = 10,
        page_index: int = 1,
    ) -> dict:
        """
        Perform search using Volcano Engine API

        Args:
            query: Search query
            page_size: Number of results (default: 10)
            page_index: Page number (default: 1)

        Returns:
            dict: API response containing search results
        """
        payload = {
            "query": query,
            "page_size": page_size,
            "page_index": page_index,
            "SearchType": "web",
        }

        response = requests.post(
            self.SEARCH_ENDPOINT, headers=self.headers, json=payload, timeout=30
        )

        if response.status_code != 200:
            error_msg = f"Volcengine Search API error: {response.status_code}"
            try:
                error_data = response.json()
                if "msg" in error_data:
                    error_msg += f" - {error_data['msg']}"
            except:
                error_msg += f" - {response.text}"
            raise Exception(error_msg)

        return response.json()


class BaiduAISearch:
    """Baidu AI Search client for intelligent search and generation"""

    BASE_URL = "https://qianfan.baidubce.com/v2/ai_search/chat/completions"

    def __init__(self, api_key: str):
        """
        Initialize Baidu AI Search client

        Args:
            api_key: Baidu Qianfan API Key (format: bce-v3/xxx or Bearer token)
        """
        self.api_key = api_key
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}" if not api_key.startswith("Bearer ") else api_key,
        }

    def search(
        self,
        query: str,
        model: str = "ernie-4.5-turbo-32k",
        search_source: str = "baidu_search_v2",
        stream: bool = False,
        enable_deep_search: bool = False,
        enable_corner_markers: bool = True,
        enable_followup_queries: bool = False,
        temperature: float = 0.11,
        top_p: float = 0.55,
        search_mode: str = "auto",
        search_recency_filter: str | None = None,
        instruction: str = "",
    ) -> dict:
        """
        Perform intelligent search using Baidu AI Search API

        Args:
            query: Search query
            model: Model to use for generation (default: ernie-4.5-turbo-32k)
            search_source: Search engine version (baidu_search_v1 or baidu_search_v2)
            stream: Whether to use streaming response
            enable_deep_search: Enable deep search for more comprehensive results
            enable_corner_markers: Enable corner markers for reference citations
            enable_followup_queries: Enable follow-up query suggestions
            temperature: Model sampling temperature (0, 1]
            top_p: Model sampling top_p (0, 1]
            search_mode: Search mode (auto, required, disabled)
            search_recency_filter: Filter by recency (week, month, semiyear, year)
            instruction: System instruction for response style
            max_completion_tokens: Maximum output tokens

        Returns:
            dict: API response containing search results and generated answer
        """
        payload = {
            "messages": [{"role": "user", "content": query}],
            "model": model,
            "search_source": search_source,
            "stream": stream,
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

        response = requests.post(self.BASE_URL, headers=self.headers, json=payload, timeout=120)

        if response.status_code != 200:
            error_data = response.json() if response.text else {}
            raise Exception(
                f"Baidu AI Search API error: {response.status_code} - "
                f"{error_data.get('message', response.text)}"
            )

        return response.json()


def _search_with_volcengine(query: str, verbose: bool = False) -> dict:
    """
    Perform search using Volcano Engine API

    Args:
        query: Search query
        verbose: Whether to print detailed information

    Returns:
        dict: Standardized search result
    """
    api_key = os.environ.get("VOLCENGINE_API_KEY")
    if not api_key:
        raise ValueError("VOLCENGINE_API_KEY environment variable is not set")

    client = VolcengineSearch(api_key=api_key)
    response = client.search(query=query)

    # Standardize result
    result = {
        "timestamp": datetime.now().isoformat(),
        "query": query,
        "provider": "volcengine",
        "answer": "",  # Volcano search API mainly returns search results, summary might need LLM
        "response": response,
        "search_results": [],
        "citations": [],
    }

    # Parse search results
    if "Result" in response and "WebResults" in response["Result"]:
        result_list = response["Result"]["WebResults"]
        for i, item in enumerate(result_list, 1):
            search_result = {
                "title": item.get("Title", ""),
                "url": item.get("Url", ""),
                "date": item.get("PublishTime", ""),
                "snippet": item.get("Snippet", "") or item.get("Summary", ""),
                "source": item.get("SiteName", ""),
            }
            result["search_results"].append(search_result)
            
            citation_data = {
                "id": i,
                "reference": f"[{i}]",
                "url": search_result["url"],
                "title": search_result["title"],
                "snippet": search_result["snippet"],
            }
            result["citations"].append(citation_data)

    if verbose:
        print(f"[Volcengine] Query: {query}")
        print(f"[Volcengine] Results found: {len(result['search_results'])}")

    return result


def _search_with_baidu(
    query: str,
    model: str = "ernie-4.5-turbo-32k",
    enable_deep_search: bool = False,
    search_recency_filter: str | None = None,
    verbose: bool = False,
) -> dict:
    """
    Perform search using Baidu AI Search API

    Args:
        query: Search query
        model: Model to use for generation
        enable_deep_search: Enable deep search
        search_recency_filter: Filter by recency
        verbose: Whether to print detailed information

    Returns:
        dict: Standardized search result
    """
    api_key = os.environ.get("BAIDU_API_KEY")
    if not api_key:
        raise ValueError(
            "BAIDU_API_KEY environment variable is not set. "
            "Please get your API key from https://console.bce.baidu.com/ai_apaas/resource"
        )

    client = BaiduAISearch(api_key=api_key)

    response = client.search(
        query=query,
        model=model,
        enable_deep_search=enable_deep_search,
        search_recency_filter=search_recency_filter,
    )

    # Extract answer from response
    answer = ""
    if response.get("choices"):
        choice = response["choices"][0]
        if choice.get("message"):
            answer = choice["message"].get("content", "")

    # Build standardized result
    result = {
        "timestamp": datetime.now().isoformat(),
        "query": query,
        "model": model,
        "provider": "baidu",
        "answer": answer,
        "response": {
            "content": answer,
            "role": "assistant",
            "finish_reason": response.get("choices", [{}])[0].get("finish_reason", ""),
        },
        "usage": {},
        "citations": [],
        "search_results": [],
        "is_safe": response.get("is_safe", True),
        "request_id": response.get("request_id", ""),
    }

    # Extract usage information
    if response.get("usage"):
        usage = response["usage"]
        result["usage"] = {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        }

    # Extract references/citations
    if response.get("references"):
        for i, ref in enumerate(response["references"], 1):
            citation_data = {
                "id": ref.get("id", i),
                "reference": f"[{ref.get('id', i)}]",
                "url": ref.get("url", ""),
                "title": ref.get("title", ""),
                "snippet": ref.get("content", ""),
                "date": ref.get("date", ""),
                "type": ref.get("type", "web"),
                "icon": ref.get("icon", ""),
                "website": ref.get("website", ""),
                "web_anchor": ref.get("web_anchor", ""),
            }
            result["citations"].append(citation_data)

            # Also add to search_results for compatibility
            search_result = {
                "title": ref.get("title", ""),
                "url": ref.get("url", ""),
                "date": ref.get("date", ""),
                "snippet": ref.get("content", ""),
                "source": ref.get("web_anchor", ""),
            }
            result["search_results"].append(search_result)

    # Extract follow-up queries if available
    if response.get("followup_queries"):
        result["followup_queries"] = response["followup_queries"]

    if verbose:
        print(f"[Baidu AI Search] Query: {query}")
        print(f"[Baidu AI Search] Model: {model}")
        print(f"[Baidu AI Search] References count: {len(result['citations'])}")

    return result


def _search_with_perplexity(query: str, verbose: bool = False) -> dict:
    """
    Perform search using Perplexity API

    Args:
        query: Search query
        verbose: Whether to print detailed information

    Returns:
        dict: Standardized search result
    """
    if not PERPLEXITY_AVAILABLE:
        raise ImportError(
            "perplexity module is not installed. To use Perplexity search, please install: "
            "pip install perplexity"
        )

    api_key = os.environ.get("PERPLEXITY_API_KEY")
    if not api_key:
        raise ValueError("PERPLEXITY_API_KEY environment variable is not set")

    if Perplexity is None:
        raise ImportError("Perplexity module is not available")

    client = Perplexity(api_key=api_key)

    completion = client.chat.completions.create(
        model="sonar",
        messages=[
            {
                "role": "system",
                "content": "You are a helpful AI assistant. Provide detailed and accurate answers based on web search results.",
            },
            {"role": "user", "content": query},
        ],
    )

    answer = completion.choices[0].message.content

    # Build usage info with safe attribute access
    usage_info: dict = {}
    if hasattr(completion, "usage") and completion.usage is not None:
        usage = completion.usage
        usage_info = {
            "prompt_tokens": getattr(usage, "prompt_tokens", 0),
            "completion_tokens": getattr(usage, "completion_tokens", 0),
            "total_tokens": getattr(usage, "total_tokens", 0),
        }
        if hasattr(usage, "cost") and usage.cost is not None:
            cost = usage.cost
            usage_info["cost"] = {
                "total_cost": getattr(cost, "total_cost", 0),
                "input_tokens_cost": getattr(cost, "input_tokens_cost", 0),
                "output_tokens_cost": getattr(cost, "output_tokens_cost", 0),
            }

    result = {
        "timestamp": datetime.now().isoformat(),
        "query": query,
        "model": completion.model,
        "provider": "perplexity",
        "answer": answer,
        "response": {
            "content": answer,
            "role": completion.choices[0].message.role,
            "finish_reason": completion.choices[0].finish_reason,
        },
        "usage": usage_info,
        "citations": [],
        "search_results": [],
    }

    # Extract citation links
    if hasattr(completion, "citations") and completion.citations:
        for i, citation_url in enumerate(completion.citations, 1):
            citation_data = {
                "id": i,
                "reference": f"[{i}]",
                "url": citation_url,
                "title": "",
                "snippet": "",
            }

            for search_item in result.get("search_results", []):
                if search_item.get("url") == citation_url:
                    citation_data["title"] = search_item.get("title", "")
                    citation_data["snippet"] = search_item.get("snippet", "")
                    break

            result["citations"].append(citation_data)

    # Extract search result details
    if hasattr(completion, "search_results") and completion.search_results:
        for search_item in completion.search_results:
            search_result = {
                "title": search_item.title,
                "url": search_item.url,
                "date": search_item.date,
                "last_updated": search_item.last_updated,
                "snippet": search_item.snippet,
                "source": search_item.source,
            }
            result["search_results"].append(search_result)

    if verbose:
        print(f"[Perplexity] Query: {query}")
        print(f"[Perplexity] Model: {completion.model}")

    return result


def web_search(
    query: str,
    output_dir: str | None = None,
    verbose: bool = False,
    # Baidu-specific options
    baidu_model: str = "ernie-4.5-turbo-32k",
    baidu_enable_deep_search: bool = False,
    baidu_search_recency_filter: str = "week",
) -> dict:
    """
    Perform network search using specified search provider and return results

    Args:
        query: Search query
        output_dir: Output directory (optional, if provided will save results)
        verbose: Whether to print detailed information
        baidu_model: Model to use for Baidu AI Search (default: ernie-4.5-turbo-32k)
        baidu_enable_deep_search: Enable deep search for Baidu (more comprehensive results)
        baidu_search_recency_filter: Filter by recency for Baidu (week, month, semiyear, year)

    Returns:
        dict: Dictionary containing search results
            {
                "query": str,
                "answer": str,
                "provider": str,
                "result_file": str (if file was saved)
            }

    Raises:
        ImportError: If required module is not installed
        ValueError: If required environment variable is not set
        Exception: If API call fails
    """
    # Get search provider from environment variable
    provider = os.environ.get("SEARCH_PROVIDER", "perplexity").lower()

    try:
        if provider == "baidu":
            result = _search_with_baidu(
                query=query,
                model=baidu_model,
                enable_deep_search=baidu_enable_deep_search,
                search_recency_filter=baidu_search_recency_filter,
                verbose=verbose,
            )
        elif provider == "perplexity":
            result = _search_with_perplexity(query=query, verbose=verbose)
        elif provider == "volcengine":
            result = _search_with_volcengine(query=query, verbose=verbose)
        else:
            raise ValueError(
                f"Unsupported search provider: {provider}. Use 'perplexity', 'baidu', or 'volcengine'."
            )

        # If output directory provided, save results
        result_file = None
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_filename = f"search_{provider}_{timestamp}.json"
            output_path = os.path.join(output_dir, output_filename)

            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)

            result_file = output_path

            if verbose:
                print(f"Search results saved to: {output_path}")

        # Add file path to result
        if result_file:
            result["result_file"] = result_file

        if verbose:
            answer = result.get("answer", "")
            print(f"Query: {query}")
            if answer:
                print(f"Answer: {answer[:200]}..." if len(answer) > 200 else f"Answer: {answer}")

        return result

    except Exception as e:
        raise Exception(f"{provider.capitalize()} API call failed: {e!s}")


if __name__ == "__main__":
    import sys

    if sys.platform == "win32":
        import io

        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    # Test with different providers
    # Default: Perplexity
    # result = web_search("What is a diffusion model?", output_dir="./test_output", verbose=True)

    # Test with Baidu AI Search
    result = web_search(
        "What is a diffusion model?",
        output_dir="./test_output",
        verbose=True,
    )
    print("\nSearch completed!")
    print(f"Provider: {result.get('provider', 'unknown')}")
    print(f"Query: {result['query']}")
    answer = result.get("answer", "")
    print(f"Answer: {answer[:300]}..." if len(answer) > 300 else f"Answer: {answer}")
