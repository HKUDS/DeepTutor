"""Model tool arguments cannot override trusted connection or output settings."""

from __future__ import annotations

from collections.abc import AsyncIterator
from importlib import import_module
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from deeptutor.core.context import UnifiedContext
from deeptutor.runtime.agentic.tool_dispatch import dispatch_tool_calls
from deeptutor.runtime.registry.tool_registry import ToolRegistry
from deeptutor.runtime.stream_bus import StreamBus
from deeptutor.services.config.provider_runtime import ResolvedSearchConfig
from deeptutor.services.search.types import WebSearchResponse


async def _dispatch(tool_name: str, arguments: dict[str, Any]) -> str:
    registry = ToolRegistry()
    registry.load_builtins()
    stream = StreamBus()
    try:
        outcome = await dispatch_tool_calls(
            tool_calls=[{"id": "call-1", "name": tool_name, "arguments": json.dumps(arguments)}],
            context=UnifiedContext(session_id="s1", user_message="Explore learning algorithms"),
            stream=stream,
            source="chat",
            stage="responding",
            iteration_index=0,
            registry=registry,
        )
        assert outcome.tool_messages
        return str(outcome.tool_messages[0]["content"])
    finally:
        await stream.close()


@pytest.fixture
def llm_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Record real tool-service requests without contacting an LLM provider."""
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "deeptutor.services.llm.config.get_llm_config",
        lambda: SimpleNamespace(
            api_key="configured-key",
            base_url="https://configured.invalid/v1",
            model="configured-model",
        ),
    )
    monkeypatch.setattr(
        "deeptutor.services.config.get_agent_params",
        lambda _name: {"max_tokens": 512, "temperature": 0.25},
    )
    monkeypatch.setattr(
        "deeptutor.services.llm.get_token_limit_kwargs",
        lambda _model, limit: {"max_tokens": limit},
    )

    async def fake_stream(**kwargs: Any) -> AsyncIterator[str]:
        calls.append(kwargs)
        yield '["learning algorithms"]'

    monkeypatch.setattr("deeptutor.services.llm.stream", fake_stream)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name", ["brainstorm", "reason", "knowledge_frontier"])
@pytest.mark.parametrize(
    "overrides",
    [
        {},
        {"base_url": "https://untrusted.invalid/v1"},
        {"api_key": "untrusted-key"},
        {"model": "untrusted-model"},
        {"max_tokens": 1, "temperature": 2.0},
    ],
    ids=["defaults", "endpoint", "credential", "model", "generation"],
)
async def test_model_calls_use_configured_llm(
    tool_name: str,
    overrides: dict[str, Any],
    llm_calls: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if tool_name == "knowledge_frontier":
        monkeypatch.setattr(
            "deeptutor.multi_user.knowledge_access.resolve_kb_manifest",
            lambda _name, **_kwargs: SimpleNamespace(name="Course", total=0, documents=()),
        )

        async def fake_rag_search(**_kwargs: Any) -> dict[str, Any]:
            return {"answer": "Course notes", "sources": []}

        async def fake_search_papers(_self: Any, **_kwargs: Any) -> list[dict[str, Any]]:
            return []

        monkeypatch.setattr("deeptutor.tools.rag_tool.rag_search", fake_rag_search)
        monkeypatch.setattr(
            "deeptutor.tools.knowledge_frontier.ArxivSearchTool.search_papers", fake_search_papers
        )
        arguments = {"kb_name": "Course", "focus": "learning algorithms"}
    else:
        arguments = {
            "topic" if tool_name == "brainstorm" else "query": "learning algorithms",
            "context": "Course notes",
        }

    await _dispatch(tool_name, {**arguments, **overrides})

    assert len(llm_calls) == 1
    request = llm_calls[0]
    assert request["base_url"] == "https://configured.invalid/v1"
    assert request["api_key"] == "configured-key"
    assert request["model"] == "configured-model"
    assert request["max_tokens"] == 512
    assert request["temperature"] == 0.25
    assert "learning algorithms" in request["prompt"]
    assert "Course notes" in request["prompt"]


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name", ["brainstorm", "reason"])
async def test_programmatic_llm_overrides_remain_available(
    tool_name: str, llm_calls: list[dict[str, Any]]
) -> None:
    tool_function = getattr(import_module(f"deeptutor.tools.{tool_name}"), tool_name)
    await tool_function(
        **{"topic" if tool_name == "brainstorm" else "query": "learning algorithms"},
        base_url="https://caller.invalid/v1",
        api_key="caller-key",
        model="caller-model",
        max_tokens=256,
        temperature=0.5,
    )

    assert len(llm_calls) == 1
    request = llm_calls[0]
    assert request["base_url"] == "https://caller.invalid/v1"
    assert request["api_key"] == "caller-key"
    assert request["model"] == "caller-model"
    assert request["max_tokens"] == 256
    assert request["temperature"] == 0.5


@pytest.mark.asyncio
async def test_model_search_cannot_write_to_an_undeclared_output_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("deeptutor.services.search._get_web_search_config", lambda: {})
    monkeypatch.setattr("deeptutor.services.search._get_source_filter_settings", lambda: {})
    monkeypatch.setattr(
        "deeptutor.services.search.resolve_search_runtime_config",
        lambda: ResolvedSearchConfig(provider="duckduckgo", requested_provider="duckduckgo"),
    )
    monkeypatch.setattr("deeptutor.services.search.search_fallback_candidates", lambda _name: [])
    monkeypatch.setattr(
        "deeptutor.services.search._run_provider",
        lambda name, query, _kwargs: (
            WebSearchResponse(query=query, answer="Search answer", provider=name),
            True,
        ),
    )
    model_output = tmp_path / "model-selected"

    answer = await _dispatch(
        "web_search", {"query": "learning algorithms", "output_dir": str(model_output)}
    )

    assert answer == "Search answer"
    assert not model_output.exists()

    # Trusted programmatic callers can still save search results explicitly.
    from deeptutor.tools.web_search import web_search

    caller_output = tmp_path / "caller-selected"
    result = web_search("learning algorithms", output_dir=str(caller_output))
    assert Path(result["result_file"]).parent == caller_output
    assert len(list(caller_output.glob("*.json"))) == 1
