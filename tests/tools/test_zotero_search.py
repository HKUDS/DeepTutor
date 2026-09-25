from __future__ import annotations

from typing import Any

import httpx
import pytest

from deeptutor.tools import zotero_search as zotero_module
from deeptutor.tools.builtin import (
    BUILTIN_TOOL_NAMES,
    USER_TOGGLEABLE_TOOL_NAMES,
    ZoteroSearchToolWrapper,
)
from deeptutor.tools.zotero_search import ZoteroSearchClient, ZoteroSearchError


class FakeResponse:
    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=httpx.Request("GET", "https://api.zotero.org"),
                response=httpx.Response(self.status_code),
            )

    def json(self) -> Any:
        return self.payload


class FakeClient:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response

    async def __aenter__(self) -> "FakeClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def get(self, url: str, *, headers: dict, params: dict) -> FakeResponse:
        self.url = url
        self.headers = headers
        self.params = params
        return self.response


def _item(title: str = "Attention Is All You Need") -> dict[str, Any]:
    return {
        "key": "OUTER1",
        "links": {"alternate": {"href": "https://www.zotero.org/users/123/items/OUTER1"}},
        "data": {
            "key": "ABCD1234",
            "itemType": "journalArticle",
            "title": title,
            "creators": [{"firstName": "Ashish", "lastName": "Vaswani"}],
            "date": "2017-06-12",
            "DOI": "10.5555/example",
            "url": "https://example.com/paper",
            "abstractNote": "A compact abstract.",
        },
    }


@pytest.mark.asyncio
async def test_zotero_client_requests_public_user_library() -> None:
    client = FakeClient(FakeResponse([_item()]))

    items = await ZoteroSearchClient(lambda: client).search(
        query="attention",
        user_id="12345",
    )

    assert client.url == "https://api.zotero.org/users/12345/items/top"
    assert "Authorization" not in client.headers
    assert client.headers["Zotero-API-Version"] == "3"
    assert client.params["q"] == "attention"
    assert client.params["qmode"] == "titleCreatorYear"
    assert items[0]["title"] == "Attention Is All You Need"
    assert items[0]["authors"] == ["Ashish Vaswani"]
    assert items[0]["year"] == "2017"
    assert items[0]["zotero_key"] == "ABCD1234"


@pytest.mark.asyncio
async def test_zotero_client_maps_private_library_auth_error() -> None:
    client = FakeClient(FakeResponse([], status_code=403))
    search = ZoteroSearchClient(lambda: client)

    with pytest.raises(ZoteroSearchError, match="invalid_api_key") as exc_info:
        await search.search(query="attention", user_id="12345", api_key="secret")

    assert exc_info.value.status_code == 403
    assert client.headers["Authorization"] == "Bearer secret"


@pytest.mark.asyncio
async def test_zotero_tool_formats_items_and_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class FakeSearchClient:
        async def search(self, **kwargs: Any) -> list[dict[str, Any]]:
            captured.update(kwargs)
            return [
                {
                    "title": "Saved Reference",
                    "item_type": "journalArticle",
                    "authors": ["Ada Lovelace"],
                    "year": "1843",
                    "doi": "10.1234/saved",
                    "url": "https://example.com",
                    "abstract": "Saved abstract.",
                    "zotero_key": "ZOT1",
                    "zotero_url": "https://www.zotero.org/users/1/items/ZOT1",
                }
            ]

    monkeypatch.setattr(zotero_module, "ZoteroSearchClient", FakeSearchClient)

    result = await ZoteroSearchToolWrapper().execute(
        query="reference",
        user_id="12345",
        api_key="secret",
    )

    expected = {
        "query": "reference",
        "user_id": "12345",
        "api_key": "secret",
        "max_results": 5,
    }
    assert captured == expected
    assert "**Saved Reference** (1843)" in result.content
    assert result.sources[0]["provider"] == "zotero"
    assert result.sources[0]["zotero_key"] == "ZOT1"


@pytest.mark.asyncio
async def test_zotero_tool_reports_missing_and_no_result_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing = await ZoteroSearchToolWrapper().execute(query="reference", user_id="")
    assert missing.success is False
    assert "user_id is required" in missing.content

    class FakeSearchClient:
        async def search(self, **kwargs: Any) -> list[dict[str, Any]]:
            return []

    monkeypatch.setattr(zotero_module, "ZoteroSearchClient", FakeSearchClient)
    empty = await ZoteroSearchToolWrapper().execute(query="reference", user_id="12345")
    assert empty.success is True
    assert empty.content == "No Zotero references matched this query."


@pytest.mark.asyncio
async def test_zotero_tool_maps_request_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingSearchClient:
        async def search(self, **kwargs: Any) -> list[dict[str, Any]]:
            raise ZoteroSearchError("request_failed", 500)

    monkeypatch.setattr(zotero_module, "ZoteroSearchClient", FailingSearchClient)

    result = await ZoteroSearchToolWrapper().execute(query="reference", user_id="12345")

    assert result.success is False
    assert result.metadata["error"] == "request_failed"
    assert result.metadata["status_code"] == 500


def test_zotero_tool_is_registered_and_user_toggleable() -> None:
    definition = ZoteroSearchToolWrapper().get_definition()
    parameters = {parameter.name: parameter for parameter in definition.parameters}

    assert definition.name == "zotero_search"
    assert definition.name in BUILTIN_TOOL_NAMES
    assert parameters["api_key"].sensitive is True
    assert parameters["max_results"].default == 5
    assert "zotero_search" in USER_TOGGLEABLE_TOOL_NAMES


@pytest.mark.parametrize("language", ["en", "zh"])
def test_zotero_prompt_hints_are_bilingual(language: str) -> None:
    hints = ZoteroSearchToolWrapper().get_prompt_hints(language=language)

    assert "Zotero" in hints.short_description
    assert hints.guideline
    assert hints.input_format
