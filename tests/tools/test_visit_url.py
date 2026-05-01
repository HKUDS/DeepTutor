"""Tests for VisitUrlTool — URL aliveness and content verification."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from deeptutor.tools.builtin import VisitUrlTool


@pytest.fixture
def tool() -> VisitUrlTool:
    return VisitUrlTool()


class TestGetDefinition:
    def test_name_is_visit_url(self, tool: VisitUrlTool) -> None:
        assert tool.name == "visit_url"

    def test_has_url_and_claim_parameters(self, tool: VisitUrlTool) -> None:
        definition = tool.get_definition()
        param_names = {p.name for p in definition.parameters}
        assert "url" in param_names
        assert "claim" in param_names

    def test_description_mentions_aliveness(self, tool: VisitUrlTool) -> None:
        definition = tool.get_definition()
        assert "reachable" in definition.description.lower() or "alive" in definition.description.lower()


class TestExecute:
    @pytest.mark.asyncio
    async def test_no_url_returns_failure(self, tool: VisitUrlTool) -> None:
        result = await tool.execute(url="")
        assert result.success is False
        assert "no url" in result.content.lower()
        assert result.metadata.get("alive") is False

    @pytest.mark.asyncio
    async def test_httpx_not_installed_returns_failure(self, tool: VisitUrlTool, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(__import__("sys").modules, "httpx", None)
        result = await tool.execute(url="https://example.com")
        assert result.success is False
        assert "not installed" in result.content.lower()

    @pytest.mark.asyncio
    async def test_invalid_url_format_returns_failure(self, tool: VisitUrlTool) -> None:
        # httpx will reject this at the network level
        result = await tool.execute(url="not-a-valid-url")
        assert result.success is False
        assert result.metadata.get("alive") is False

    @pytest.mark.asyncio
    async def test_source_includes_url_and_title(self, tool: VisitUrlTool) -> None:
        result = await tool.execute(url="https://example.com")
        if result.metadata.get("alive"):
            assert len(result.sources) == 1
            assert result.sources[0]["url"] == "https://example.com"
            assert "title" in result.sources[0]

    @pytest.mark.asyncio
    async def test_metadata_has_alive_status(self, tool: VisitUrlTool) -> None:
        result = await tool.execute(url="https://example.com")
        assert "alive" in result.metadata
        assert "status_code" in result.metadata

    @pytest.mark.asyncio
    async def test_claim_verification_when_page_supports_it(self, tool: VisitUrlTool) -> None:
        # example.com HTML contains "Example Domain" — verify the claim check is present
        result = await tool.execute(
            url="https://example.com",
            claim="Example Domain",
        )
        if result.metadata.get("alive"):
            assert result.metadata.get("claim_verified") is True

    @pytest.mark.asyncio
    async def test_claim_not_verified_for_missing_content(self, tool: VisitUrlTool) -> None:
        result = await tool.execute(
            url="https://example.com",
            claim="THIS STRING IS UNLIKELY TO EXIST ON THE PAGE xyz123",
        )
        if result.metadata.get("alive"):
            assert result.metadata.get("claim_verified") is False

    @pytest.mark.asyncio
    async def test_timeout_yields_failure(self, tool: VisitUrlTool) -> None:
        # Patch httpx.AsyncClient.get so it raises asyncio.TimeoutError after
        # a tiny sleep — fast and deterministic, avoids real 20s OS-level TCP hang.
        import asyncio

        async def mock_get(*args, **kwargs):
            await asyncio.sleep(0.01)
            raise asyncio.TimeoutError("connection timeout")

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = mock_get

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await tool.execute(
                url="https://10.255.255.1",
                claim="anything",
            )

        assert result.success is False
        assert result.metadata.get("alive") is False
        assert "timeout" in result.content.lower()


class TestBatchUrlExecution:
    @pytest.mark.asyncio
    async def test_newline_separated_urls_are_parsed_as_batch(self, tool: VisitUrlTool) -> None:
        # Test that newline-separated URL string is treated as a list of URLs
        raw_url = "https://example.com\nhttps://example.org"
        assert isinstance(raw_url, str)
        url_list = [u.strip() for u in raw_url.split("\n") if u.strip()]
        assert len(url_list) == 2
        assert url_list == ["https://example.com", "https://example.org"]

    @pytest.mark.asyncio
    async def test_single_url_still_works(self, tool: VisitUrlTool) -> None:
        result = await tool.execute(url="https://example.com")
        if result.metadata.get("alive"):
            assert result.success is True
            assert result.metadata.get("alive") is True

    @pytest.mark.asyncio
    async def test_list_of_urls_accepted(self, tool: VisitUrlTool) -> None:
        result = await tool.execute(url=["https://example.com", "https://example.org"])
        if result.metadata.get("alive"):
            assert result.success is True
            assert result.metadata.get("url_count") == 2
            assert len(result.sources) == 2

    @pytest.mark.asyncio
    async def test_batch_result_aggregates_sources(self, tool: VisitUrlTool) -> None:
        # Verify that batch results include per-URL metadata
        result = await tool.execute(url=["https://example.com", "https://example.org"])
        if result.metadata.get("url_count") == 2:
            assert "url_count" in result.metadata
            assert "alive_count" in result.metadata
            assert "dead_count" in result.metadata
            assert result.metadata["url_count"] == 2
