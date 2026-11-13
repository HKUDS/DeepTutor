"""Server-owned tool arguments never cross the model boundary (issue #2610).

Two concrete holes from the upstream RFC:

* ``reason`` / ``brainstorm`` / ``knowledge_frontier`` read ``api_key`` /
  ``base_url`` / ``model`` from tool-call arguments and threaded them into
  the server-side LLM call — the model could pick which endpoint its data
  was sent to and spend a credential of its choosing.
* ``web_search`` read ``output_dir`` from tool-call arguments and the search
  service ``mkdir -p``-ed and wrote there — an arbitrary-directory write.

``_drop_server_owned_args`` strips those names from model-supplied tool
arguments so the implementations resolve the values from the server-side
configuration layer only. The one server-side exception — the pipelines'
task-workspace storage for ``web_search`` — travels on the private
``_web_search_output_dir`` channel, which the pipelines plain-assign over
anything the model sent.

Patch targets are resolved with :func:`importlib.import_module` on purpose:
``deeptutor.tools`` lazily re-exports ``reason``/``brainstorm``/``web_search``
as module attributes, so dotted monkeypatch strings can resolve to the
re-exported *functions* instead of the submodules.
"""

from __future__ import annotations

import importlib
import logging
from types import SimpleNamespace
from typing import Any

import pytest

from deeptutor.tools.builtin import (
    SERVER_OWNED_TOOL_ARG_NAMES,
    BrainstormTool,
    KnowledgeFrontierTool,
    ReasonTool,
    WebSearchTool,
    _drop_server_owned_args,
)

_SMUGGLED_LLM_ARGS = {
    "api_key": "sk-model-chosen",
    "base_url": "https://attacker.example/v1",
    "model": "attacker-model",
}


def _tool_module(name: str) -> Any:
    return importlib.import_module(f"deeptutor.tools.{name}")


# ---------------------------------------------------------------------------
# The shared strip helper
# ---------------------------------------------------------------------------


class TestDropServerOwnedArgs:
    def test_strips_every_server_owned_name_and_keeps_the_rest(self) -> None:
        args = {
            "query": "attention",
            "api_key": "sk-model-chosen",
            "base_url": "https://attacker.example/v1",
            "model": "attacker-model",
            "output_dir": "/tmp/attacker",
        }
        cleaned = _drop_server_owned_args(args, tool_name="web_search")
        assert cleaned == {"query": "attention"}
        # Exactly the brief's list: a future rename must widen this set on
        # purpose, never by accident.
        assert SERVER_OWNED_TOOL_ARG_NAMES == {"api_key", "base_url", "model", "output_dir"}

    def test_legitimate_arguments_pass_through_untouched(self) -> None:
        args = {
            "query": "q",
            "context": "c",
            "kb_name": "kb",
            "max_tokens": 512,
            "temperature": 0.3,
        }
        assert _drop_server_owned_args(args) == args

    def test_does_not_mutate_the_callers_mapping(self) -> None:
        args = {"query": "q", "api_key": "sk-model-chosen"}
        cleaned = _drop_server_owned_args(args)
        assert "api_key" not in cleaned
        assert args == {"query": "q", "api_key": "sk-model-chosen"}

    def test_smuggle_attempt_is_logged_without_values(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING, logger="deeptutor.tools.builtin"):
            _drop_server_owned_args(
                {
                    "query": "q",
                    "api_key": "sk-secret-value",
                    "base_url": "https://attacker.example",
                },
                tool_name="reason",
            )
        message = caplog.records[-1].getMessage()
        assert "api_key" in message and "base_url" in message and "reason" in message
        assert "sk-secret-value" not in message
        assert "attacker.example" not in message


# ---------------------------------------------------------------------------
# The model-visible schemas never advertise server-owned parameters
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tool_cls",
    [BrainstormTool, ReasonTool, WebSearchTool, KnowledgeFrontierTool],
)
class TestModelVisibleSchemas:
    def test_schema_never_advertises_server_owned_parameters(self, tool_cls: type) -> None:
        advertised = {param.name for param in tool_cls().get_definition().parameters}
        assert not advertised & SERVER_OWNED_TOOL_ARG_NAMES


# ---------------------------------------------------------------------------
# Hole 1 — reason / brainstorm: model-chosen endpoint, key and model
# ---------------------------------------------------------------------------


def _patch_server_llm_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the server-side LLM profile the implementations must fall back to."""
    from deeptutor.services.llm.config import LLMConfig

    llm_config_module = importlib.import_module("deeptutor.services.llm.config")
    monkeypatch.setattr(
        llm_config_module,
        "get_llm_config",
        lambda: LLMConfig(
            model="server-model",
            api_key="sk-server",
            base_url="https://api.server.example/v1",
        ),
    )
    services_config_module = importlib.import_module("deeptutor.services.config")
    monkeypatch.setattr(services_config_module, "get_agent_params", lambda name: {})


def _capture_llm_stream(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    streamed: list[dict[str, Any]] = []

    async def fake_stream(**kwargs: Any):
        streamed.append(dict(kwargs))
        yield "server-config answer"

    llm_package = importlib.import_module("deeptutor.services.llm")
    monkeypatch.setattr(llm_package, "stream", fake_stream)
    return streamed


class TestReasonToolBoundary:
    @pytest.mark.asyncio
    async def test_model_supplied_endpoint_and_credentials_are_dropped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: list[dict[str, Any]] = []

        async def fake_reason(**kwargs: Any) -> dict[str, Any]:
            captured.append(dict(kwargs))
            return {
                "query": kwargs.get("query", ""),
                "answer": "reasoned",
                "model": "server-model",
            }

        monkeypatch.setattr(_tool_module("reason"), "reason", fake_reason)

        result = await ReasonTool().execute(
            query="derive the closed form",
            context="prior work",
            **_SMUGGLED_LLM_ARGS,
        )

        assert result.success
        assert result.content == "reasoned"
        (call,) = captured
        assert call["query"] == "derive the closed form"
        assert call["context"] == "prior work"
        assert not SERVER_OWNED_TOOL_ARG_NAMES & call.keys()

    @pytest.mark.asyncio
    async def test_unbroken_chain_resolves_the_llm_from_server_config(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Per-hole check of the reason.py call chain: what reaches the wire."""
        _patch_server_llm_config(monkeypatch)
        streamed = _capture_llm_stream(monkeypatch)

        await ReasonTool().execute(query="derive the closed form", **_SMUGGLED_LLM_ARGS)

        (call,) = streamed
        assert call["model"] == "server-model"
        assert call["api_key"] == "sk-server"
        assert call["base_url"] == "https://api.server.example/v1"
        assert "attacker" not in str(call)


class TestBrainstormToolBoundary:
    @pytest.mark.asyncio
    async def test_model_supplied_endpoint_and_credentials_are_dropped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: list[dict[str, Any]] = []

        async def fake_brainstorm(**kwargs: Any) -> dict[str, Any]:
            captured.append(dict(kwargs))
            return {"topic": kwargs.get("topic", ""), "answer": "ideas", "model": "server-model"}

        monkeypatch.setattr(_tool_module("brainstorm"), "brainstorm", fake_brainstorm)

        result = await BrainstormTool().execute(topic="study plans", **_SMUGGLED_LLM_ARGS)

        assert result.success
        assert result.content == "ideas"
        (call,) = captured
        assert call["topic"] == "study plans"
        assert not SERVER_OWNED_TOOL_ARG_NAMES & call.keys()

    @pytest.mark.asyncio
    async def test_unbroken_chain_resolves_the_llm_from_server_config(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_server_llm_config(monkeypatch)
        streamed = _capture_llm_stream(monkeypatch)

        await BrainstormTool().execute(topic="study plans", **_SMUGGLED_LLM_ARGS)

        (call,) = streamed
        assert call["model"] == "server-model"
        assert call["api_key"] == "sk-server"
        assert call["base_url"] == "https://api.server.example/v1"
        assert "attacker" not in str(call)


# ---------------------------------------------------------------------------
# Hole 1 — knowledge_frontier: smuggled args must not reach reason()
# ---------------------------------------------------------------------------


def _stub_kb_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = SimpleNamespace(
        name="Course",
        total=2,
        documents=(
            SimpleNamespace(name="attention-basics.pdf"),
            SimpleNamespace(name="curriculum.md"),
        ),
    )
    knowledge_access = importlib.import_module("deeptutor.multi_user.knowledge_access")
    monkeypatch.setattr(
        knowledge_access,
        "resolve_kb_manifest",
        lambda kb_name, **_kwargs: manifest,
        raising=False,
    )

    async def fake_rag_search(query: str, kb_name: str) -> dict[str, Any]:
        return {"answer": "The KB covers attention basics.", "sources": []}

    class FakeArxivSearchTool:
        async def search_papers(self, **kwargs: Any) -> list[dict[str, Any]]:
            return [
                {
                    "title": "Grounded Frontier Learning",
                    "authors": ["Ada Lovelace"],
                    "year": 2026,
                    "abstract": "A recent direction.",
                    "url": "https://arxiv.org/abs/2601.0001",
                    "arxiv_id": "2601.0001",
                }
            ]

    monkeypatch.setattr(_tool_module("rag_tool"), "rag_search", fake_rag_search)
    monkeypatch.setattr(_tool_module("knowledge_frontier"), "ArxivSearchTool", FakeArxivSearchTool)


class TestKnowledgeFrontierToolBoundary:
    @pytest.mark.asyncio
    async def test_model_supplied_llm_args_never_reach_the_reasoning_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        reason_calls: list[dict[str, Any]] = []

        async def fake_reason(**kwargs: Any) -> dict[str, Any]:
            reason_calls.append(dict(kwargs))
            return {
                "answer": 'Here are queries: ["attention mechanisms"]',
                "model": "server-model",
            }

        _stub_kb_runtime(monkeypatch)
        monkeypatch.setattr(_tool_module("reason"), "reason", fake_reason)

        result = await KnowledgeFrontierTool().execute(
            kb_name="Course",
            focus="curriculum design",
            **_SMUGGLED_LLM_ARGS,
        )

        # The tool still works end to end — stripping changes nothing about
        # its own contract.
        assert result.success
        assert result.metadata["status"] == "papers_found"
        assert result.metadata["queries"] == ["attention mechanisms"]
        (call,) = reason_calls
        assert not SERVER_OWNED_TOOL_ARG_NAMES & call.keys()

    @pytest.mark.asyncio
    async def test_unbroken_chain_resolves_the_llm_from_server_config(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_server_llm_config(monkeypatch)
        streamed = _capture_llm_stream(monkeypatch)
        _stub_kb_runtime(monkeypatch)

        result = await KnowledgeFrontierTool().execute(
            kb_name="Course",
            focus="curriculum design",
            **_SMUGGLED_LLM_ARGS,
        )

        assert result.success
        (call,) = streamed
        assert call["model"] == "server-model"
        assert call["api_key"] == "sk-server"
        assert call["base_url"] == "https://api.server.example/v1"
        assert "attacker" not in str(call)


# ---------------------------------------------------------------------------
# Hole 2 — web_search: model-chosen output_dir
# ---------------------------------------------------------------------------


class TestWebSearchToolBoundary:
    @pytest.mark.asyncio
    async def test_model_supplied_output_dir_is_dropped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: list[dict[str, Any]] = []

        def fake_web_search(**kwargs: Any) -> dict[str, Any]:
            captured.append(dict(kwargs))
            return {"answer": "found", "citations": []}

        monkeypatch.setattr(_tool_module("web_search"), "web_search", fake_web_search)

        result = await WebSearchTool().execute(
            query="latest news",
            output_dir="C:/Users/attacker/Desktop",
        )

        assert result.success
        assert result.content == "found"
        (call,) = captured
        assert call["query"] == "latest news"
        assert not SERVER_OWNED_TOOL_ARG_NAMES & call.keys()

    @pytest.mark.asyncio
    async def test_server_side_storage_channel_still_reaches_the_service(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The pipelines' task-workspace storage keeps working — it travels
        on the private ``_web_search_output_dir`` channel, which the model
        cannot win: the augmenters plain-assign it over anything supplied."""
        captured: list[dict[str, Any]] = []

        def fake_web_search(**kwargs: Any) -> dict[str, Any]:
            captured.append(dict(kwargs))
            return {"answer": "found", "citations": []}

        monkeypatch.setattr(_tool_module("web_search"), "web_search", fake_web_search)

        await WebSearchTool().execute(
            query="latest news",
            output_dir="C:/Users/attacker/Desktop",
            _web_search_output_dir="C:/server/task/web_search",
        )

        (call,) = captured
        assert call["output_dir"] == "C:/server/task/web_search"
        assert "attacker" not in str(call)


class TestWebSearchServiceDefaultBehaviour:
    """The service layer's own contract is unchanged: no directory, no write;
    an explicit server-side caller still gets its results saved."""

    @pytest.fixture
    def saved_writes(self, monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
        from deeptutor.services.config.provider_runtime import ResolvedSearchConfig
        from deeptutor.services.search.types import Citation, WebSearchResponse
        import deeptutor.services.search as search_service

        monkeypatch.setattr(search_service, "_get_web_search_config", lambda: {})

        def fake_resolve() -> ResolvedSearchConfig:
            return ResolvedSearchConfig(provider="duckduckgo", requested_provider="duckduckgo")

        monkeypatch.setattr(search_service, "resolve_search_runtime_config", fake_resolve)

        def fake_run_provider(provider_name: str, query: str, provider_kwargs: dict[str, Any]):
            response = WebSearchResponse(
                query=query,
                answer="summary",
                provider=provider_name,
                citations=[Citation(id=1, reference="[1]", url="https://example.com")],
            )
            return response, True

        monkeypatch.setattr(search_service, "_run_provider", fake_run_provider)
        monkeypatch.setattr(search_service, "_get_source_filter_settings", lambda: {})

        saved: list[tuple[str, str]] = []

        def fake_save(result: dict[str, Any], output_dir: str, provider: str) -> str:
            saved.append((output_dir, provider))
            return f"{output_dir}/search_{provider}.json"

        monkeypatch.setattr(search_service, "_save_results", fake_save)
        return saved

    def test_without_output_dir_nothing_is_written(self, saved_writes) -> None:
        from deeptutor.services.search import web_search

        result = web_search(query="hello")
        assert saved_writes == []
        assert "result_file" not in result

    def test_server_side_caller_can_still_direct_the_write(self, saved_writes, tmp_path) -> None:
        from deeptutor.services.search import web_search

        target = tmp_path / "server-chosen"
        result = web_search(query="hello", output_dir=str(target))
        assert saved_writes == [(str(target), "duckduckgo")]
        assert result["result_file"] == f"{target}/search_duckduckgo.json"
