"""Isolated, inference-free Claude SDK model discovery for both adapters."""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from typing import Any


def parse_models(rows: list) -> list[dict[str, str]]:
    models = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        value = str(row.get("value") or "").strip()
        if not value or value == "default" or row.get("disabled") or row.get("isDisabled"):
            continue
        if row.get("available") is False:
            continue
        slug = str(row.get("resolvedModel") or value).strip()
        if value.endswith("[1m]") and not slug.endswith("[1m]"):
            slug += "[1m]"
        if not slug or slug in seen:
            continue
        seen.add(slug)
        models.append({"slug": slug, "display_name": str(row.get("displayName") or slug)})
    return models


async def discover_models() -> list[dict[str, str]]:
    # Keep the SDK optional; CLI-only installs retain the existing fallback.
    from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

    options: dict[str, Any] = {
        "tools": [],
        "setting_sources": [],
        "permission_mode": "dontAsk",
        "extra_args": {"strict-mcp-config": None},
    }
    cli = shutil.which("claude")
    if cli:
        options["cli_path"] = cli
    # Do not discover project files, hooks, or MCP servers from the repo whose
    # settings page initiated sync. Authentication stays CLI-managed.
    async with asyncio.timeout(15):
        return await _discover_in_directory(ClaudeAgentOptions, ClaudeSDKClient, options)


async def _discover_in_directory(ClaudeAgentOptions, ClaudeSDKClient, options):
    with tempfile.TemporaryDirectory(prefix="dt-claude-model-sdk-") as directory:
        options["cwd"] = directory
        async with ClaudeSDKClient(options=ClaudeAgentOptions(**options)) as client:
            info = await client.get_server_info() or {}
            return parse_models(info.get("models") or [])
