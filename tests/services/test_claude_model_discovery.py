import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from deeptutor.services.llm import claude_sdk
from deeptutor.services.subagent import claude_models as module

ROWS = [
    {"value": "default", "resolvedModel": "claude-opus-test", "displayName": "Default"},
    {"value": "opus", "resolvedModel": "claude-opus-test", "displayName": "Opus Test"},
    {"value": "fable", "resolvedModel": "claude-fable-test", "displayName": "Fable Test"},
    {"value": "claude-haiku-older", "displayName": "Haiku Older"},
    {"value": "sonnet", "resolvedModel": "claude-sonnet-test", "displayName": "Sonnet Test"},
    {
        "value": "sonnet[1m]",
        "resolvedModel": "claude-sonnet-test",
        "displayName": "Sonnet Test (1M)",
    },
    {"value": "blocked", "disabled": True},
    {"value": "unavailable", "available": False},
]


def test_sdk_catalog_keeps_all_versions_and_context_variants():
    models = claude_sdk.parse_models([*ROWS, ROWS[1], {}, "invalid"])
    assert [m["slug"] for m in models] == [
        "claude-opus-test",
        "claude-fable-test",
        "claude-haiku-older",
        "claude-sonnet-test",
        "claude-sonnet-test[1m]",
    ]
    assert models[1]["display_name"] == "Fable Test"


@pytest.fixture
def sdk(monkeypatch):
    state = SimpleNamespace(closed=False, fail=False)

    class Client:
        def __init__(self, options):
            state.options = options

        async def __aenter__(self):
            self.owner = asyncio.current_task()
            return self

        async def __aexit__(self, *args):
            assert self.owner is asyncio.current_task()
            state.closed = True

        async def get_server_info(self):
            if state.fail:
                raise ValueError("Unusable initialization")
            return {"models": ROWS, "account": {"private": "not model metadata"}}

        async def query(self, *args):
            raise AssertionError("Model discovery must not send an inference request")

    monkeypatch.setitem(
        sys.modules,
        "claude_agent_sdk",
        SimpleNamespace(ClaudeSDKClient=Client, ClaudeAgentOptions=lambda **kw: kw),
    )
    monkeypatch.setattr(claude_sdk.shutil, "which", lambda command: "/native/claude")
    return state


@pytest.mark.asyncio
async def test_sdk_discovery_closes_in_owner_task_and_does_not_return_account_data(sdk):
    models = await module._discover_sdk_models()
    assert models == claude_sdk.parse_models(ROWS)
    assert sdk.closed
    assert sdk.options["cli_path"] == "/native/claude"
    assert sdk.options["tools"] == []
    assert sdk.options["setting_sources"] == []
    assert sdk.options["extra_args"] == {"strict-mcp-config": None}
    assert not Path(sdk.options["cwd"]).exists()
    assert "private" not in str(models)


@pytest.mark.asyncio
async def test_failed_initialization_still_closes_the_client(sdk):
    sdk.fail = True
    with pytest.raises(ValueError):
        await module._discover_sdk_models()
    assert sdk.closed
    assert not Path(sdk.options["cwd"]).exists()


@pytest.fixture
def cache(monkeypatch, tmp_path):
    path = tmp_path / "models.json"
    monkeypatch.setattr(module, "_cache_path", lambda: path)
    return path


@pytest.mark.asyncio
async def test_sdk_sync_caches_results_without_starting_terminal_capture(monkeypatch, cache):
    async def discover():
        return claude_sdk.parse_models(ROWS)

    monkeypatch.setattr(module, "_discover_sdk_models", discover)
    monkeypatch.setattr(
        module, "_capture_model_screen", lambda: pytest.fail("Unexpected TUI capture")
    )
    result = await module.sync_claude_models()
    assert result == module.load_cached_claude_models()
    assert result[0][1]["slug"] == "claude-fable-test"


@pytest.mark.asyncio
async def test_missing_sdk_falls_back_to_terminal_picker_including_fable(monkeypatch, cache):
    async def missing():
        raise ImportError("SDK not installed")

    monkeypatch.setattr(module, "_discover_sdk_models", missing)
    monkeypatch.setattr(
        module,
        "_capture_model_screen",
        lambda: "Select model\n 1. Fable  Fable Test · Complex tasks",
    )
    models, stamp = await module.sync_claude_models()
    assert models == [{"slug": "fable", "display_name": "Fable Test"}]
    assert stamp


@pytest.mark.asyncio
async def test_both_discovery_failures_preserve_existing_cache(monkeypatch, cache):
    module._write_cache([{"slug": "previous", "display_name": "Previous"}], "previous-stamp")
    original = cache.read_bytes()

    async def empty():
        return []

    monkeypatch.setattr(module, "_discover_sdk_models", empty)
    monkeypatch.setattr(module, "_capture_model_screen", lambda: None)
    assert await module.sync_claude_models() == ([], "")
    assert cache.read_bytes() == original


@pytest.mark.asyncio
async def test_sdk_timeout_cancels_discovery_before_fallback(monkeypatch, cache):
    stopped = asyncio.Event()

    async def stalled():
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    monkeypatch.setattr(module, "_discover_sdk_models", stalled)
    monkeypatch.setattr(module, "_SDK_CAPTURE_TIMEOUT", 0.01)
    monkeypatch.setattr(module, "_capture_model_screen", lambda: None)
    assert await module.sync_claude_models() == ([], "")
    assert stopped.is_set()


@pytest.mark.asyncio
async def test_user_cancellation_does_not_launch_fallback(monkeypatch, cache):
    async def cancelled():
        raise asyncio.CancelledError()

    monkeypatch.setattr(module, "_discover_sdk_models", cancelled)
    monkeypatch.setattr(
        module, "_capture_model_screen", lambda: pytest.fail("Cancelled sync must stop")
    )
    with pytest.raises(asyncio.CancelledError):
        await module.sync_claude_models()
