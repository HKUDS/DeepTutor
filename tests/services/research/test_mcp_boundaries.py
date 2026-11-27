from types import SimpleNamespace

import pytest

from deeptutor.core.tool_protocol import BaseTool, ToolDefinition, ToolResult
from deeptutor.runtime.providers.allowlist import Allowlist
from deeptutor.runtime.registry.scoped_registry import ScopedToolRegistry
from deeptutor.services.mcp.config import MCPConfig, MCPServerConfig
import deeptutor.services.mcp.network as network
from deeptutor.services.mcp.user_config import UserMcpError, _assert_self_service_allowed
from deeptutor.tools.research_tools import PreprintTool


@pytest.fixture
def approval(monkeypatch):
    config = MCPConfig(
        servers={
            "reviewed": MCPServerConfig(
                url="http://research.internal:8080/mcp", allow_private_network=True, enabled=False
            )
        }
    )
    monkeypatch.setattr("deeptutor.services.mcp.config.load_mcp_config", lambda: config)

    def addresses(host, *args):
        ip = {
            "research.internal": "172.18.0.4",
            "other.internal": "10.0.0.8",
            "metadata.internal": "169.254.169.254",
            "mapped.internal": "::ffff:169.254.169.254",
            "loopback.internal": "127.0.0.1",
            "aws.internal": "fd00:ec2::254",
            "alibaba.internal": "100.100.100.200",
        }[host]
        return [(2, 1, 6, "", (ip, 0))]

    monkeypatch.setattr(network.socket, "getaddrinfo", addresses)
    return config


def test_private_exception_needs_exact_admin_origin_and_does_not_expand_to_other_hosts(approval):
    cfg = MCPServerConfig(url="http://research.internal:8080/mcp", allow_private_network=True)
    _assert_self_service_allowed("research", cfg, validate_url=True)
    assert not network.validate_mcp_url(cfg.url, strict=True)[0]
    origin = network.approved_private_origin(cfg.url)
    assert network.validate_mcp_url(cfg.url, strict=True, trusted_origin=origin)[0]
    assert not network.validate_mcp_url(
        "http://other.internal:8080/mcp", strict=True, trusted_origin=origin
    )[0]
    assert not network.validate_mcp_url(
        "http://research.internal:8081/mcp", strict=True, trusted_origin=origin
    )[0]
    approval.servers["reviewed"].allow_private_network = False
    with pytest.raises(UserMcpError, match="administrator approval"):
        _assert_self_service_allowed("research", cfg, validate_url=True)


@pytest.mark.parametrize(
    "host",
    [
        "metadata.internal",
        "mapped.internal",
        "loopback.internal",
        "aws.internal",
        "alibaba.internal",
    ],
)
def test_trust_never_allows_metadata_or_self_service_loopback(approval, host):
    url = f"http://{host}:8080/mcp"
    assert not network.validate_mcp_url(url, strict=True, trusted_origin=network.mcp_origin(url))[0]


class Reader(BaseTool):
    provider_kind = "mcp"
    deferred = True
    _original_name = "get_paper_content"

    def __init__(self):
        self.calls = []

    def get_definition(self):
        return ToolDefinition(name="mcp_research_get_paper_content", description="Read paper")

    async def execute(self, **kwargs):
        self.calls.append(kwargs)
        return ToolResult(content="source text")


class Registry:
    def __init__(self, tool):
        self.tool = tool

    def get(self, name):
        return self.tool if name == self.tool.name else None

    async def execute(self, name, **kwargs):
        return await self.tool.execute(**kwargs)


@pytest.mark.asyncio
async def test_research_mcp_respects_dispatch_grants_and_requests_primary_text():
    reader = Reader()
    base = Registry(reader)
    denied = ScopedToolRegistry(base=base, allowed=Allowlist.of([]))
    result = await PreprintTool().execute(
        action="mcp",
        mcp_tool=reader.name,
        arguments={"url": "https://arxiv.org/abs/1706.03762"},
        _research_registry=denied,
    )
    assert not result.success and not reader.calls
    allowed = ScopedToolRegistry(base=base, allowed=Allowlist.unrestricted())
    result = await PreprintTool().execute(
        action="mcp",
        mcp_tool=reader.name,
        arguments={"url": "https://arxiv.org/abs/1706.03762"},
        _research_registry=allowed,
    )
    assert result.success and reader.calls[0]["fullText"] is True
    reader._original_name = "delete_folder"
    result = await PreprintTool().execute(
        action="mcp", mcp_tool=reader.name, _research_registry=allowed
    )
    assert not result.success and len(reader.calls) == 1


@pytest.mark.asyncio
async def test_community_annotations_are_kept_in_their_own_evidence_layer():
    reader = Reader()
    reader._original_name = "get_comments"
    result = await PreprintTool().execute(
        action="mcp",
        mcp_tool=reader.name,
        arguments={"paper": "1706.03762"},
        _research_registry=Registry(reader),
    )
    assert result.metadata["source_layer"] == "community_annotation"


@pytest.mark.asyncio
async def test_a_pooled_private_connection_cannot_invoke_after_admin_revocation(approval):
    from deeptutor.services.mcp.manager import MCPConnectionManager

    called = []
    cfg = MCPServerConfig(url="http://research.internal:8080/mcp", allow_private_network=True)
    connection = SimpleNamespace(config=cfg, status="connected", session=object())
    manager = MCPConnectionManager.__new__(MCPConnectionManager)
    manager._connections = {("owner", "research"): connection}

    async def invoke(*args):
        called.append(True)
        return "source evidence"

    manager._call_watching_connection = invoke
    assert (
        await manager.call_tool("owner", "research", "get_paper_content", {}, timeout=30)
        == "source evidence"
    )
    approval.servers["reviewed"].allow_private_network = False
    assert "revoked" in await manager.call_tool(
        "owner", "research", "get_paper_content", {}, timeout=30
    )
    assert called == [True]


@pytest.mark.asyncio
async def test_transport_guards_real_http_hooks_and_redirects(approval, monkeypatch):
    from contextlib import AsyncExitStack, asynccontextmanager

    import httpx
    from mcp.client import streamable_http

    from deeptutor.services.mcp.manager import SHARED_OWNER, MCPConnectionManager

    captured = []

    @asynccontextmanager
    async def transport(url, *, http_client):
        captured.append(http_client)
        yield None, None, None

    monkeypatch.setattr(streamable_http, "streamable_http_client", transport)
    for owner in ["owner", SHARED_OWNER]:
        async with AsyncExitStack() as stack:
            cfg = MCPServerConfig(
                url="http://research.internal:8080/mcp", allow_private_network=True
            )
            await MCPConnectionManager._open_transport(stack, cfg, owner=owner)
            guard = captured[-1].event_hooks["request"][0]
            await guard(httpx.Request("POST", cfg.url))
            with pytest.raises(ValueError, match="Blocked"):
                await guard(httpx.Request("GET", "http://metadata.internal:8080/mcp"))
            with pytest.raises(ValueError, match="Blocked"):
                await guard(httpx.Request("GET", "http://other.internal:8080/mcp"))


@pytest.mark.asyncio
async def test_live_shared_adapter_replaces_the_same_sources_stale_schema(monkeypatch):
    from deeptutor.services.mcp.manager import SHARED_OWNER

    old, current = Reader(), Reader()
    old._owner = current._owner = SHARED_OWNER
    monkeypatch.setattr(Reader, "owner", property(lambda self: self._owner), raising=False)
    monkeypatch.setattr(Reader, "provider_id", "research", raising=False)
    registry = ScopedToolRegistry(
        base=Registry(old), overlay=[current], allowed=Allowlist.unrestricted()
    )
    assert registry.get(current.name) is current
    await registry.execute(current.name, url="source")
    assert not old.calls and len(current.calls) == 1
