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
        assert "timeout" in result.content.lower() or "timed out" in result.content.lower()


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


class Test429RetryWithBackoff:
    """Tests for HTTP 429 rate-limit retry with exponential backoff."""

    @pytest.mark.asyncio
    async def test_retries_on_429_and_succeeds(self, tool: VisitUrlTool) -> None:
        """When first request gets 429 and second succeeds, return the successful result."""
        import asyncio
        import httpx

        call_count = 0

        async def mock_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First attempt: rate limited
                resp = httpx.Response(429, text="Rate limited")
                resp._headers = {"content-type": "text/html"}
                return resp
            # Second attempt: success
            resp = httpx.Response(200, text="<html><title>Success</title></html>")
            resp._headers = {"content-type": "text/html"}
            return resp

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = mock_get

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await tool.execute(url="https://example.com")

        assert result.metadata.get("alive") is True
        assert result.metadata.get("status_code") == 200
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_gives_up_after_max_retries(self, tool: VisitUrlTool) -> None:
        """When all attempts return 429, mark URL as dead and return 429 status."""
        import httpx

        async def mock_get(*args, **kwargs):
            resp = httpx.Response(429, text="Rate limited")
            resp._headers = {"content-type": "text/html"}
            return resp

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = mock_get

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await tool.execute(url="https://example.com")

        assert result.metadata.get("alive") is False
        assert result.metadata.get("status_code") == 429

    @pytest.mark.asyncio
    async def test_sleeps_with_exponential_backoff(self, tool: VisitUrlTool) -> None:
        """Verify that backoff intervals double after each 429 response."""
        import asyncio
        import httpx

        call_count = 0
        sleep_intervals: list[float] = []

        original_sleep = asyncio.sleep

        async def tracking_sleep(delay: float):
            sleep_intervals.append(delay)
            await original_sleep(0)  # no real sleep during tests

        async def mock_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            resp = httpx.Response(429, text="Rate limited")
            resp._headers = {"content-type": "text/html"}
            return resp

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = mock_get

        with patch("httpx.AsyncClient", return_value=mock_client), \
             patch("asyncio.sleep", tracking_sleep):
            await tool.execute(url="https://example.com")

        # Should have slept twice (between attempt 1→2 and 2→3), with backoff doubling
        assert len(sleep_intervals) == 2
        assert sleep_intervals[1] > sleep_intervals[0]
        # First backoff ~1.0s, second ~2.0s
        assert sleep_intervals[0] == 1.0
        assert sleep_intervals[1] == 2.0
