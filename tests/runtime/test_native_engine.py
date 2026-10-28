"""Native execution across real private pipes and a local HTTP model fixture."""

import asyncio
from contextvars import ContextVar
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from deeptutor.runtime.ts_engine.client import EngineClient

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None
    or not (
        Path(__file__).parents[2] / "packages/chat-engine/dist/src/transport/stdio.js"
    ).is_file(),
    reason="Build the experimental TypeScript engine first",
)
SCOPE = ContextVar("native_fixture_scope", default="missing")


@pytest_asyncio.fixture
async def native():
    requests, writers = [], set()
    entered = asyncio.Event()

    async def handle(reader, writer):
        writers.add(writer)
        try:
            headers = (await reader.readuntil(b"\r\n\r\n")).decode()
            size = next(
                int(x.split(":", 1)[1])
                for x in headers.splitlines()
                if x.lower().startswith("content-length:")
            )
            body = json.loads(await reader.readexactly(size))
            requests.append(body)
            text = json.dumps(body["messages"])
            if not body.get("stream"):
                reply = json.dumps(
                    {
                        "choices": [
                            {
                                "message": {"content": "Native fixture answer"},
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": {"prompt_tokens": 12, "completion_tokens": 4},
                    }
                ).encode()
                writer.write(
                    b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: "
                    + str(len(reply)).encode()
                    + b"\r\n\r\n"
                    + reply
                )
                await writer.drain()
                return
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nConnection: close\r\n\r\n"
            )
            if (
                "source-native-fixture" in text
                and body.get("tools")
                and not any(m["role"] == "tool" for m in body["messages"])
            ):
                delta = {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "source-1",
                            "function": {
                                "name": "read_source",
                                "arguments": '{"source_id":"nb-1","source_index":{"nb-1":"forged"}}',
                            },
                        }
                    ]
                }
                finish = "tool_calls"
            elif "tool-fixture" in text and not any(m["role"] == "tool" for m in body["messages"]):
                delta = {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call-1",
                            "function": {
                                "name": "legacy_fixture",
                                "arguments": '{"value":1,"_owner":"forged"}',
                            },
                        }
                    ]
                }
                finish = "tool_calls"
            else:
                delta, finish = {"content": "Native fixture answer"}, "stop"
            if "stall-fixture" in text:
                finish = None
            writer.write(
                (
                    "data: "
                    + json.dumps({"choices": [{"delta": delta, "finish_reason": finish}]})
                    + "\n\n"
                ).encode()
            )
            await writer.drain()
            entered.set()
            if finish is None:
                await reader.read()
            else:
                writer.write(b"data: [DONE]\n\n")
                await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            writers.discard(writer)
            writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    client = EngineClient()
    yield SimpleNamespace(
        client=client,
        endpoint=f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1/chat/completions",
        requests=requests,
        entered=entered,
    )
    await client.close()
    server.close()
    await server.wait_closed()
    for writer in tuple(writers):
        writer.close()
        await writer.wait_closed()


def payload(endpoint, text="plain fixture"):
    return {
        "config": {"explorationBudget": 3, "settlementBudget": 3, "emptyRecoveryBudget": 2},
        "provider": {
            "endpoint": endpoint,
            "apiKey": "fixture",
            "headers": {},
            "model": "fixture",
            "format": "chat_completions",
            "completion": {"max_tokens": 128},
            "stream": True,
            "maxConcurrency": 20,
            "requestsPerMinute": 600,
        },
        "seed": {
            "system": "fixture",
            "history": [],
            "snapshots": {},
            "user": {"role": "user", "content": text},
            "contextWindow": 32000,
            "outputTokens": 128,
            "model": "fixture",
            "route": {},
        },
        "tools": [
            {
                "schema": {
                    "type": "function",
                    "function": {"name": "legacy_fixture", "parameters": {}},
                },
                "native": False,
                "sensitive": [],
            }
        ],
        "source": "chat",
        "stage": "responding",
        "sessionId": "fixture",
        "workspace": None,
        "skillRoots": {},
        "rebindingTools": [],
        "deferOutput": False,
        "policyHooks": False,
        "initialToolChoice": None,
        "copy": {},
    }


class Port:
    def __init__(self):
        self.seen = []

    async def invoke(self, operation, args, state):
        self.seen.append((operation, SCOPE.get(), args))
        if operation in {"event", "checkpoint"}:
            return None
        if operation == "after_tools":
            return {}
        assert operation == "legacy_tool"
        assert args["args"] == {"value": 1}
        return {
            "content": "effect committed",
            "success": True,
            "metadata": {},
            "sources": [],
            "pause": None,
            "terminate": False,
            "modelMessage": None,
        }


@pytest.mark.asyncio
async def test_native_model_and_tools_keep_concurrent_owner_context(native):
    async def run(owner):
        token = SCOPE.set(owner)
        try:
            port = Port()
            result = await native.client.run_native(port, payload(native.endpoint, "tool-fixture"))
            assert result["response"] == "Native fixture answer"
            assert result["legacyToolCalls"] == 1
            assert all(scope == owner for _, scope, _ in port.seen)
            assert sum(op == "legacy_tool" for op, _, _ in port.seen) == 1
            assert not any(op in {"call_round", "dispatch_tools"} for op, _, _ in port.seen)
        finally:
            SCOPE.reset(token)

    await asyncio.gather(*(run(f"owner-{i}/workspace-{i}") for i in range(8)))
    assert len(native.requests) == 16


@pytest.mark.asyncio
async def test_native_cancel_and_worker_loss_never_replay(native):
    from deeptutor.services.llm.exceptions import LLMProviderTransportError

    task = asyncio.create_task(
        native.client.run_native(Port(), payload(native.endpoint, "stall-fixture"))
    )
    # Cold worker startup is not the cancellation deadline; allow CI process scheduling.
    await asyncio.wait_for(native.entered.wait(), 10)
    native.client._process.kill()
    with pytest.raises(LLMProviderTransportError) as raised:
        await asyncio.wait_for(task, 2)
    assert raised.value.partial_response
    assert len(native.requests) == 1
    native.entered.clear()
    task = asyncio.create_task(
        native.client.run_native(Port(), payload(native.endpoint, "stall-fixture"))
    )
    # Cold worker startup is not the cancellation deadline; allow CI process scheduling.
    await asyncio.wait_for(native.entered.wait(), 10)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    result = await native.client.run_native(Port(), payload(native.endpoint))
    assert result["completed"]
    assert len(native.requests) == 3


@pytest.mark.asyncio
async def test_native_history_uses_selected_branch_and_advances_summary_only_for_summarized_rows(
    native, monkeypatch
):
    from deeptutor.services.llm.config import LLMConfig
    from deeptutor.services.session import context_builder as module
    import deeptutor.services.session.native_history as bridge

    monkeypatch.setenv("DEEPTUTOR_CHAT_ENGINE", "typescript-native")
    monkeypatch.setattr(bridge, "get_engine_client", lambda: native.client)
    monkeypatch.setattr(
        module,
        "count_tokens",
        lambda _: pytest.fail("Native history must not load Python tokenization"),
    )
    rows = [
        {
            "id": i + 1,
            "role": "user" if i % 2 == 0 else "assistant",
            "content": f"branch-specific-{i} " + "detail " * 200,
        }
        for i in range(12)
    ]
    store = SimpleNamespace(
        get_session=AsyncMock(
            return_value={"compressed_summary": "sibling-only-secret", "summary_up_to_msg_id": 999}
        ),
        get_messages_for_context=AsyncMock(return_value=rows),
        update_summary=AsyncMock(),
    )
    result = await module.ContextBuilder(store).build(
        session_id="fixture",
        llm_config=LLMConfig(
            binding="openai",
            model="fixture",
            api_key="fixture",
            base_url=native.endpoint.removesuffix("/chat/completions"),
            context_window=4096,
        ),
        leaf_message_id=12,
    )
    store.get_messages_for_context.assert_awaited_once_with("fixture", leaf_message_id=12)
    store.update_summary.assert_awaited_once()
    assert 0 < store.update_summary.call_args.args[2] < 12
    assert result.conversation_summary == "Native fixture answer"
    assert "sibling-only-secret" not in json.dumps(native.requests)
    assert any("branch-specific-11" in str(m["content"]) for m in result.model_history)


def test_unsupported_providers_are_routed_before_native_effects(monkeypatch):
    from dataclasses import replace

    from deeptutor.runtime.ts_engine.config import compatibility_reason
    from deeptutor.services.llm.config import LLMConfig

    for name in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(
        "deeptutor.services.config.load_system_settings", lambda: {"disable_ssl_verify": False}
    )

    config = LLMConfig(
        binding="openai", model="gpt-4o-mini", api_key="fixture", base_url="http://fixture/v1"
    )
    assert compatibility_reason(config) == ""
    assert compatibility_reason(replace(config, wire_api="responses")) == "Responses API"
    assert compatibility_reason(replace(config, api_key=["a", "b"])) == "API key pool"
    assert compatibility_reason(replace(config, provider_mode="oauth"))
    assert (
        compatibility_reason(replace(config, api_version="2025-01-01"))
        == "Azure deployment authentication"
    )
    monkeypatch.setenv("HTTPS_PROXY", "http://fixture-proxy")
    assert compatibility_reason(config) == "custom proxy or certificate configuration"
    monkeypatch.delenv("HTTPS_PROXY")
    monkeypatch.setattr(
        "deeptutor.services.config.load_system_settings", lambda: {"disable_ssl_verify": True}
    )
    assert compatibility_reason(config) == "custom TLS configuration"


@pytest.mark.asyncio
async def test_source_investigation_uses_shared_ts_loop_and_never_publishes_answer(
    native, monkeypatch
):
    from deeptutor.capabilities.explore_context import explorer as module
    from deeptutor.capabilities.explore_context.capability import _load_prompts
    from deeptutor.core.context import UnifiedContext
    from deeptutor.core.stream import StreamEventType
    from deeptutor.runtime.stream_bus import StreamBus
    from deeptutor.services.llm.config import LLMConfig
    from deeptutor.tools.builtin import ReadSourceTool

    cfg = LLMConfig(
        model="gpt-4o-mini",
        api_key="fixture",
        base_url=native.endpoint.removesuffix("/chat/completions"),
    )
    monkeypatch.setenv("DEEPTUTOR_CHAT_ENGINE", "typescript-native")
    monkeypatch.setattr(module, "get_llm_config", lambda: cfg)
    monkeypatch.setattr("deeptutor.runtime.ts_engine.config.compatibility_reason", lambda _: "")
    monkeypatch.setattr(
        "deeptutor.capabilities.explore_context.native.get_engine_client", lambda: native.client
    )
    source_tool = ReadSourceTool()
    registry = SimpleNamespace(
        get=lambda name: source_tool,
        build_openai_schemas=lambda _: [source_tool.get_definition().to_openai_schema()],
    )
    monkeypatch.setattr(module, "get_tool_registry", lambda: registry)
    explorer = module.ContextExplorer(language="en", prompts=_load_prompts("en"))
    explorer._run_loop = AsyncMock(side_effect=AssertionError("Python loop must not run"))
    explorer._single_pass = AsyncMock(side_effect=AssertionError("Python fallback must not run"))
    context = UnifiedContext(
        session_id="source-fixture",
        user_message="source-native-fixture",
        source_manifest="nb-1 authorized note",
        metadata={"source_index": {"nb-1": "Scoped note 😀"}},
    )
    stream = StreamBus()
    usage = SimpleNamespace(add_from_response=lambda entry: counts.append(entry))
    counts = []
    answer = await explorer.investigate(context=context, stream=stream, usage=usage)
    assert "Native fixture answer" in answer
    assert len(native.requests) == 2
    assert any(m.get("content") == "Scoped note 😀" for m in native.requests[1]["messages"])
    assert context.runtime.model_turn is None
    events = stream._history
    assert not any(e.type == StreamEventType.CONTENT for e in events)
    assert any(e.type == StreamEventType.THINKING for e in events)
    assert any(
        e.type == StreamEventType.TOOL_RESULT and e.content == "Scoped note 😀" for e in events
    )
    assert len(counts) == 2
    explorer._run_loop.assert_not_called()
    explorer._single_pass.assert_not_called()


@pytest.mark.asyncio
async def test_native_service_stream_shares_worker_and_preserves_outcome(native, monkeypatch):
    from deeptutor.services.llm.config import LLMConfig
    from deeptutor.services.llm.provider_core.typescript_provider import TypeScriptProvider

    monkeypatch.setattr("deeptutor.runtime.ts_engine.get_engine_client", lambda: native.client)
    monkeypatch.setattr("deeptutor.runtime.ts_engine.config.compatibility_reason", lambda _: "")
    provider = TypeScriptProvider(
        LLMConfig(
            model="gpt-4o-mini",
            api_key="fixture",
            base_url=native.endpoint.removesuffix("/chat/completions"),
        )
    )
    chunks = []

    async def receive(text):
        chunks.append(text)

    response = await provider.chat_stream_with_retry(
        messages=[{"role": "user", "content": "service fixture"}],
        on_content_delta=receive,
        max_tokens=64,
        temperature=0.3,
        retry_delays=(),
        response_format={"type": "json_object"},
    )
    assert response.content == "Native fixture answer" == "".join(chunks)
    assert response.finish_reason == "stop"
    assert response.provider_specific_fields["execution_runtime"] == "typescript-native"
    assert len(native.requests) == 1
    assert native.requests[0]["temperature"] == 0.3
    assert (
        native.requests[0].get("max_tokens", native.requests[0].get("max_completion_tokens")) == 64
    )
    assert native.requests[0]["response_format"] == {"type": "json_object"}
    assert "_retry_delays" not in native.requests[0]


@pytest.mark.asyncio
async def test_native_service_cancellation_does_not_retry(native, monkeypatch):
    from deeptutor.services.llm.config import LLMConfig
    from deeptutor.services.llm.provider_core.typescript_provider import TypeScriptProvider

    monkeypatch.setattr("deeptutor.runtime.ts_engine.get_engine_client", lambda: native.client)
    monkeypatch.setattr("deeptutor.runtime.ts_engine.config.compatibility_reason", lambda _: "")
    provider = TypeScriptProvider(
        LLMConfig(
            model="gpt-4o-mini",
            api_key="fixture",
            base_url=native.endpoint.removesuffix("/chat/completions"),
        )
    )
    seen = asyncio.Event()

    async def receive(text):
        seen.set()

    task = asyncio.create_task(
        provider.chat_stream_with_retry(
            messages=[{"role": "user", "content": "stall-fixture"}],
            on_content_delta=receive,
            retry_delays=(0.001, 0.001),
        )
    )
    await asyncio.wait_for(seen.wait(), 3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(native.requests) == 1


@pytest.mark.asyncio
async def test_native_service_selects_rich_request_compatibility_before_effects(monkeypatch):
    from deeptutor.services.llm.config import LLMConfig
    from deeptutor.services.llm.provider_core.base import LLMResponse
    from deeptutor.services.llm.provider_core.typescript_provider import TypeScriptProvider

    cfg = LLMConfig(model="gpt-4o-mini", api_key="fixture", base_url="http://fixture/v1")
    fallback = SimpleNamespace(
        _call_with_retry=AsyncMock(return_value=LLMResponse(content="image result")),
        chat_stream=AsyncMock(),
        aclose=AsyncMock(),
    )

    def build(config, **kwargs):
        assert kwargs == {"configure_env": False, "native_enabled": False}
        return fallback

    monkeypatch.setattr("deeptutor.services.llm.provider_factory._build_runtime_provider", build)
    provider = TypeScriptProvider(cfg)
    response = await provider.chat_stream_with_retry(
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": "https://example.com/image.png"}}
                ],
            }
        ]
    )
    assert response.content == "image result"
    fallback._call_with_retry.assert_awaited_once()
    fallback.aclose.assert_awaited_once()


def test_native_service_factory_selects_without_importing_sdk(monkeypatch):
    from deeptutor.services.llm.config import LLMConfig
    from deeptutor.services.llm.provider_core.typescript_provider import TypeScriptProvider
    from deeptutor.services.llm.provider_factory import _build_runtime_provider

    monkeypatch.setenv("DEEPTUTOR_CHAT_ENGINE", "typescript-native")
    monkeypatch.setattr("deeptutor.runtime.ts_engine.config.compatibility_reason", lambda _: "")
    cfg = LLMConfig(model="gpt-4o-mini", api_key="fixture", base_url="http://fixture/v1")
    assert isinstance(_build_runtime_provider(cfg), TypeScriptProvider)


def test_embedding_config_import_does_not_load_execution_sdks(tmp_path):
    import os
    import subprocess
    import sys

    env = {**os.environ, "DEEPTUTOR_HOME": str(tmp_path)}
    subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; from deeptutor.services.embedding import get_embedding_config; "
                "assert callable(get_embedding_config); "
                "assert 'openai' not in sys.modules; "
                "assert 'deeptutor.services.embedding.client' not in sys.modules"
            ),
        ],
        check=True,
        env=env,
        capture_output=True,
        text=True,
    )


def test_partner_memory_admission_uses_assigned_relationship_scopes(monkeypatch, tmp_path):
    from deeptutor.agents.loop.native_memory import memory_roots

    shared = SimpleNamespace(get_memory_dir=lambda: tmp_path / "assigned-human")
    own = SimpleNamespace(get_memory_dir=lambda: tmp_path / "relationship")
    monkeypatch.setattr(
        "deeptutor.services.partners.interaction.get_partner_turn_context",
        lambda: SimpleNamespace(shared_memory=shared, own_memory=own),
    )
    assert memory_roots("partner_read") == [
        str((tmp_path / "assigned-human").resolve()),
        str((tmp_path / "relationship").resolve()),
    ]


@pytest.mark.asyncio
async def test_native_service_factory_nonstream_completion(native, monkeypatch):
    from deeptutor.services.llm.config import LLMConfig
    from deeptutor.services.llm.factory import complete_with_config

    monkeypatch.setenv("DEEPTUTOR_CHAT_ENGINE", "typescript-native")
    monkeypatch.setattr("deeptutor.runtime.ts_engine.get_engine_client", lambda: native.client)
    monkeypatch.setattr("deeptutor.runtime.ts_engine.config.compatibility_reason", lambda _: "")
    cfg = LLMConfig(
        model="gpt-4o-mini",
        api_key="fixture",
        base_url=native.endpoint.removesuffix("/chat/completions"),
    )
    result = await complete_with_config(cfg, prompt="Service completion", max_retries=0)
    assert result == "Native fixture answer"
    assert len(native.requests) == 1
    assert native.requests[0]["stream"] is False


def test_model_tool_admission_resolves_prompts_and_keeps_custom_augmentation(monkeypatch):
    from deeptutor.agents.loop.native_tools import tool_runtime
    from deeptutor.services.llm.config import LLMConfig

    monkeypatch.setattr("deeptutor.runtime.ts_engine.config.compatibility_reason", lambda _: "")
    monkeypatch.setattr("deeptutor.services.config.get_agent_params", lambda _name: {})
    cfg = LLMConfig(model="gpt-4o-mini", api_key="fixture", base_url="http://fixture/v1")
    pipeline = SimpleNamespace(
        llm_config=cfg,
        model=cfg.model,
        binding=cfg.binding,
        _augment_tool_kwargs=lambda name, args, context: {"context": "server context"},
        _capability_rebinding_tools=lambda context: set(),
    )
    specs = [
        {"schema": {"function": {"name": name}}, "native": True}
        for name in ["reason", "brainstorm"]
    ]
    runtime = tool_runtime(pipeline, object(), specs)
    assert "deep reasoning engine" in runtime["reason"]["system"]
    assert "breadth-first brainstorming engine" in runtime["brainstorm"]["system"]
    assert runtime["brainstorm"]["context"] == "server context"
    assert runtime["brainstorm"]["provider"]["apiKey"] == "fixture"
    pipeline._augment_tool_kwargs = lambda name, args, context: {"custom_policy": True}
    assert tool_runtime(pipeline, object(), specs) == {}
    assert not any(spec["native"] for spec in specs)
