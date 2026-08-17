"""Unit tests for the GraphRAG local RAG pipeline + provider routing.

GraphRAG itself is an optional dependency that is NOT installed in CI, so these
tests exercise everything that does not require the package (factory routing,
config bridge, ingestion, storage, lifecycle gating) directly, and stub the thin
``engine`` adapter to cover the index/search orchestration without graphrag.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys

import pytest

from deeptutor.services.rag.factory import (
    GRAPHRAG_PROVIDER,
    get_pipeline,
    list_pipelines,
    normalize_provider_name,
)
from deeptutor.services.rag.index_versioning import resolve_storage_dir_for_read
from deeptutor.services.rag.pipelines.graphrag import config as gr_config
from deeptutor.services.rag.pipelines.graphrag import engine, ingestion, storage
from deeptutor.services.rag.pipelines.graphrag.errors import (
    GraphRagEmbeddingDimensionError,
    GraphRagEmbeddingEndpointError,
    GraphRagEmbeddingProviderUnsupportedError,
    GraphRagStructuredOutputTruncatedError,
    classify_embedding_error,
)
from deeptutor.services.rag.pipelines.graphrag.pipeline import GraphRagPipeline, _context_to_sources

# --------------------------------------------------------------------------- #
# factory routing
# --------------------------------------------------------------------------- #


def test_factory_dispatches_graphrag_lazily(tmp_path) -> None:
    imported_before = sys.modules.get("graphrag")
    pipe = get_pipeline("graphrag", kb_base_dir=str(tmp_path))
    assert type(pipe).__name__ == "GraphRagPipeline"
    # Building the pipeline must NOT import the heavy optional dependency.
    assert sys.modules.get("graphrag") is imported_before


def test_list_pipelines_includes_graphrag() -> None:
    entry = next(p for p in list_pipelines() if p["id"] == GRAPHRAG_PROVIDER)
    assert entry["requires_api_key"] is False
    assert entry["configured"] is gr_config.is_graphrag_available()


def test_normalize_provider_keeps_graphrag() -> None:
    assert normalize_provider_name("graphrag") == "graphrag"
    assert normalize_provider_name("GraphRAG") == "graphrag"


def test_ragservice_routes_graphrag_from_metadata(tmp_path) -> None:
    from deeptutor.services.rag.service import RAGService

    kb = tmp_path / "kbg"
    kb.mkdir()
    (kb / "metadata.json").write_text(json.dumps({"rag_provider": "graphrag"}), encoding="utf-8")

    svc = RAGService(kb_base_dir=str(tmp_path))
    assert svc._resolve_provider("kbg") == "graphrag"


# --------------------------------------------------------------------------- #
# config bridge
# --------------------------------------------------------------------------- #


class _Cfg:
    def __init__(
        self,
        model,
        url,
        key,
        dim=3072,
        binding="openai",
        *,
        extra_headers=None,
        reasoning_effort=None,
        send_dimensions=None,
    ):
        self.model = model
        self.effective_url = url
        self.base_url = None
        self.api_key = key
        self.dim = dim
        self.binding = binding
        self.provider_name = binding
        self.extra_headers = extra_headers or {}
        self.reasoning_effort = reasoning_effort
        self.send_dimensions = send_dimensions


def test_build_settings_bridges_models() -> None:
    settings = gr_config.build_settings(
        llm_cfg=_Cfg("gpt-4o-mini", "https://api.example.com/v1", "sk-llm"),
        embedding_cfg=_Cfg(
            "Qwen/Qwen3-Embedding-8B",
            "https://emb.example.com/v1",
            "sk-emb",
            dim=4096,
        ),
    )
    chat = settings["completion_models"]["default_completion_model"]
    emb = settings["embedding_models"]["default_embedding_model"]
    assert chat == {
        "type": "deeptutor_litellm",
        "model_provider": "openai",
        "model": "gpt-4o-mini",
        "auth_method": "api_key",
        "api_base": "https://api.example.com/v1",
        "api_key": "sk-llm",
    }
    assert emb["model"] == "Qwen/Qwen3-Embedding-8B"
    assert settings["input"]["type"] == "text"
    assert settings["vector_store"]["type"] == "lancedb"
    assert settings["vector_store"]["vector_size"] == 4096


@pytest.mark.parametrize(
    ("binding", "model", "reasoning_effort", "expected"),
    [
        (
            "deepseek",
            "deepseek-v4-pro",
            None,
            {
                "reasoning_effort": "high",
                "extra_body": {"thinking": {"type": "enabled"}},
            },
        ),
        (
            "deepseek",
            "deepseek-v4-flash",
            None,
            {"extra_body": {"thinking": {"type": "disabled"}}},
        ),
        (
            "dashscope",
            "qwen3-235b-a22b",
            None,
            {"extra_body": {"enable_thinking": True}},
        ),
        (
            "custom",
            "deepseek-v4-pro",
            "minimal",
            {"extra_body": {"thinking": {"type": "disabled"}}},
        ),
    ],
)
def test_build_settings_reuses_deeptutor_reasoning_request_options(
    binding: str,
    model: str,
    reasoning_effort: str | None,
    expected: dict,
) -> None:
    settings = gr_config.build_settings(
        llm_cfg=_Cfg(
            model,
            "https://chat.test/v1",
            "sk-llm",
            binding=binding,
            reasoning_effort=reasoning_effort,
            extra_headers={"X-Route": "blue"},
        ),
        embedding_cfg=_Cfg("embedding-model", "https://emb.test/v1", "sk-emb"),
    )

    call_args = settings["completion_models"][gr_config.COMPLETION_MODEL_ID]["call_args"]
    assert call_args == {"extra_headers": {"X-Route": "blue"}, **expected}


@pytest.mark.parametrize(
    ("binding", "model", "send_dimensions", "expected_dimensions"),
    [
        ("openai", "text-embedding-3-large", None, 1536),
        ("siliconflow", "Qwen/Qwen3-Embedding-8B", None, 4096),
        ("custom", "vendor/opaque-embedding", True, 768),
        ("openai", "text-embedding-3-large", False, None),
        ("custom", "vendor/opaque-embedding", None, None),
    ],
)
def test_build_settings_preserves_embedding_request_options(
    binding: str,
    model: str,
    send_dimensions: bool | None,
    expected_dimensions: int | None,
) -> None:
    dimension = expected_dimensions or (1536 if "text-embedding-3" in model else 768)
    settings = gr_config.build_settings(
        llm_cfg=_Cfg("gpt-4o-mini", "https://chat.test/v1", "sk-llm"),
        embedding_cfg=_Cfg(
            model,
            "https://emb.test/v1/embeddings",
            "sk-emb",
            dim=dimension,
            binding=binding,
            send_dimensions=send_dimensions,
            extra_headers={"X-Route": "blue"},
        ),
    )

    entry = settings["embedding_models"][gr_config.EMBEDDING_MODEL_ID]
    call_args = entry["call_args"]
    assert call_args["extra_headers"] == {"X-Route": "blue"}
    assert call_args.get("dimensions") == expected_dimensions


@pytest.mark.parametrize(
    ("binding", "endpoint", "expected"),
    [
        ("openai", "https://api.openai.com/v1/embeddings", "https://api.openai.com/v1"),
        (
            "siliconflow",
            "https://api.siliconflow.cn/v1/embeddings/",
            "https://api.siliconflow.cn/v1",
        ),
        (
            "gemini",
            "https://generativelanguage.googleapis.com/v1beta/openai/embeddings",
            "https://generativelanguage.googleapis.com/v1beta/openai",
        ),
        ("openrouter", "https://openrouter.ai/api/v1/embeddings", "https://openrouter.ai/api/v1"),
        ("orcarouter", "https://api.orcarouter.ai/v1/embeddings", "https://api.orcarouter.ai/v1"),
        ("vllm", "http://localhost:8000/v1/embeddings", "http://localhost:8000/v1"),
        ("jina", "https://api.jina.ai/v1/embeddings", "https://api.jina.ai/v1"),
        ("custom", "https://gateway.test/v1/embeddings", "https://gateway.test/v1"),
        ("openai", "https://api.openai.com/v1", "https://api.openai.com/v1"),
        ("custom", "https://gateway.test/embed", "https://gateway.test/embed"),
        (
            "custom",
            "https://gateway.test/v1/embeddings?api-key=secret",
            "https://gateway.test/v1/embeddings?api-key=secret",
        ),
    ],
)
def test_graphrag_embedding_api_base_only_normalizes_openai_compatible_operation_urls(
    binding: str, endpoint: str, expected: str
) -> None:
    assert gr_config.graphrag_embedding_api_base(binding, endpoint) == expected


@pytest.mark.parametrize(
    ("binding", "endpoint"),
    [
        ("cohere", "https://api.cohere.com/v2/embed"),
        ("ollama", "http://localhost:11434/api/embed"),
        (
            "aliyun",
            "https://dashscope.aliyuncs.com/api/v1/services/embeddings/"
            "text-embedding/text-embedding",
        ),
        (
            "azure_openai",
            "https://example.openai.azure.com/openai/deployments/embed/embeddings"
            "?api-version=2024-02-01",
        ),
        (
            "gemini",
            "https://generativelanguage.googleapis.com/v1beta/models/"
            "gemini-embedding-2:batchEmbedContents",
        ),
    ],
)
def test_graphrag_settings_reject_native_embedding_transports_without_mutating_them(
    binding: str, endpoint: str
) -> None:
    embedding_cfg = _Cfg("embedding-model", endpoint, "sk-emb", binding=binding)

    with pytest.raises(GraphRagEmbeddingProviderUnsupportedError):
        gr_config.build_settings(
            llm_cfg=_Cfg("gpt-4o-mini", "https://api.example.com/v1", "sk-llm"),
            embedding_cfg=embedding_cfg,
        )

    assert embedding_cfg.effective_url == endpoint


def test_graphrag_settings_accept_gemini_openai_compatible_endpoint() -> None:
    settings = gr_config.build_settings(
        llm_cfg=_Cfg("gpt-4o-mini", "https://api.example.com/v1", "sk-llm"),
        embedding_cfg=_Cfg(
            "gemini-embedding-001",
            "https://generativelanguage.googleapis.com/v1beta/openai/embeddings",
            "sk-emb",
            binding="gemini",
        ),
    )

    embedding = settings["embedding_models"][gr_config.EMBEDDING_MODEL_ID]
    assert embedding["api_base"] == ("https://generativelanguage.googleapis.com/v1beta/openai")


def test_build_settings_normalizes_embedding_endpoint_only_in_graphrag_payload() -> None:
    embedding_cfg = _Cfg(
        "Qwen/Qwen3-Embedding-8B",
        "https://api.siliconflow.cn/v1/embeddings",
        "sk-emb",
        dim=4096,
        binding="siliconflow",
    )

    settings = gr_config.build_settings(
        llm_cfg=_Cfg("gpt-4o-mini", "https://api.example.com/v1", "sk-llm"),
        embedding_cfg=embedding_cfg,
    )

    emb = settings["embedding_models"]["default_embedding_model"]
    assert emb["api_base"] == "https://api.siliconflow.cn/v1"
    assert embedding_cfg.effective_url == "https://api.siliconflow.cn/v1/embeddings"


def test_build_settings_requires_models() -> None:
    with pytest.raises(gr_config.GraphRagNotConfiguredError):
        gr_config.build_settings(
            llm_cfg=_Cfg("", "u", "k"),
            embedding_cfg=_Cfg("e", "u", "k"),
        )


def test_build_settings_requires_embedding_dimension() -> None:
    with pytest.raises(gr_config.GraphRagNotConfiguredError, match="known dimension"):
        gr_config.build_settings(
            llm_cfg=_Cfg("m", "u", "k"),
            embedding_cfg=_Cfg("e", "u", "k", dim=0),
        )


def test_build_settings_does_not_guess_compatibility_from_model_name(monkeypatch) -> None:
    monkeypatch.setattr(
        "deeptutor.services.llm.capabilities.supports_response_format",
        lambda _binding, _model: False,
    )

    settings = gr_config.build_settings(
        llm_cfg=_Cfg(
            "deepseek-v4-flash",
            "https://gateway.example.com/v1",
            "sk-test",
            binding="openrouter",
        ),
        embedding_cfg=_Cfg("embedding-model", "https://emb.test/v1", "sk-test"),
    )

    assert settings["completion_models"]["default_completion_model"]["model"] == "deepseek-v4-flash"


def test_local_api_key_placeholder_when_missing() -> None:
    settings = gr_config.build_settings(
        llm_cfg=_Cfg("m", "u", ""),
        embedding_cfg=_Cfg("e", "u", ""),
    )
    assert settings["completion_models"]["default_completion_model"]["api_key"] == (
        "sk-no-key-required"
    )


def test_engine_entry_points_run_on_a_private_loop() -> None:
    """GraphRAG's LLM layer patches the *current* loop at import time and
    refuses uvloop — the loop uvicorn[standard] runs the backend on. Every
    entry point must therefore execute on its own plain-asyncio loop, off the
    caller's (issue #695)."""
    seen: dict[str, object] = {}

    async def work() -> str:
        seen["running"] = asyncio.get_running_loop()
        seen["current"] = asyncio.get_event_loop()
        return "done"

    async def caller() -> str:
        seen["outer"] = asyncio.get_running_loop()
        return await engine._run_isolated(work)

    assert asyncio.run(caller()) == "done"
    assert seen["running"] is not seen["outer"]
    # ``nest_asyncio2.apply()`` patches whatever ``get_event_loop()`` returns,
    # so the private loop has to be the thread's current one, not just running.
    assert seen["current"] is seen["running"]


def test_compatibility_probe_resolves_candidate_without_mutating_active_model(
    monkeypatch, tmp_path: Path
) -> None:
    from deeptutor.services.config.model_catalog import ModelCatalogService
    from deeptutor.services.rag.pipelines.graphrag import compatibility

    catalog = {
        "version": 1,
        "services": {
            "llm": {
                "active_profile_id": "profile-a",
                "active_model_id": "model-a",
                "profiles": [
                    {
                        "id": "profile-a",
                        "name": "OpenAI",
                        "binding": "openai",
                        "base_url": "https://api.openai.com/v1",
                        "api_key": "sk-test",
                        "api_version": "",
                        "extra_headers": {},
                        "models": [
                            {"id": "model-a", "name": "A", "model": "gpt-4o-mini"},
                            {"id": "model-b", "name": "B", "model": "gpt-4.1-mini"},
                        ],
                    }
                ],
            }
        },
    }
    service = ModelCatalogService(tmp_path / "model_catalog.json")
    service.save(catalog)
    monkeypatch.setattr(compatibility, "get_model_catalog_service", lambda: service)

    captured: dict[str, object] = {}

    async def _probe(llm_cfg) -> dict:
        captured["model"] = llm_cfg.model
        captured["api_key"] = llm_cfg.api_key
        return {
            "status": "compatible",
            "compatible": True,
            "code": "graphrag_model_compatible",
            "message": "The model returned valid GraphRAG structured output.",
            "model": llm_cfg.model,
            "binding": llm_cfg.binding,
            "retryable": False,
        }

    monkeypatch.setattr(engine, "probe_completion_model", _probe, raising=False)

    result = asyncio.run(compatibility.probe_configured_completion_model("profile-a", "model-b"))

    assert result["compatible"] is True
    assert captured == {"model": "gpt-4.1-mini", "api_key": "sk-test"}
    persisted = service.load()
    assert persisted["services"]["llm"]["active_model_id"] == "model-a"


def test_completion_probe_requires_graphrag_structured_response(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _CommunityReportResponse:
        pass

    class _Response:
        formatted_response = _CommunityReportResponse()

    class _Completion:
        async def completion_async(self, **kwargs):
            captured.update(kwargs)
            return _Response()

    monkeypatch.setattr(
        engine,
        "_create_probe_completion",
        lambda _cfg: (_Completion(), _CommunityReportResponse),
        raising=False,
    )

    asyncio.run(
        engine._probe_completion_model_impl(
            _Cfg("gpt-4o-mini", "https://api.example.com/v1", "sk-test")
        )
    )

    assert captured["response_format"] is _CommunityReportResponse
    assert captured["stream"] is False
    assert captured["max_tokens"] == 1024
    assert captured["timeout"] == 25
    assert "community report" in str(captured["messages"]).lower()


def test_completion_probe_reports_compatible_after_isolated_validation(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def _impl(llm_cfg) -> None:
        captured["model"] = llm_cfg.model

    async def _isolated(work) -> None:
        captured["isolated"] = True
        await work()

    monkeypatch.setattr(engine, "_probe_completion_model_impl", _impl)
    monkeypatch.setattr(engine, "_run_isolated", _isolated)

    result = asyncio.run(
        engine.probe_completion_model(
            _Cfg(
                "gpt-4o-mini",
                "https://api.openai.com/v1",
                "sk-test",
                binding="openai",
            )
        )
    )

    assert captured == {"isolated": True, "model": "gpt-4o-mini"}
    assert result == {
        "status": "compatible",
        "compatible": True,
        "code": "graphrag_model_compatible",
        "message": "The model returned valid GraphRAG structured output.",
        "model": "gpt-4o-mini",
        "binding": "openai",
        "retryable": False,
    }


def test_completion_probe_reports_unsupported_schema_as_incompatible(monkeypatch) -> None:
    class UnsupportedParamsError(Exception):
        pass

    async def _isolated(_work) -> None:
        raise UnsupportedParamsError("response_format rejected; sk-secret-must-not-leak")

    monkeypatch.setattr(engine, "_run_isolated", _isolated)

    result = asyncio.run(
        engine.probe_completion_model(
            _Cfg(
                "candidate-model",
                "https://api.example.com/v1",
                "sk-secret-must-not-leak",
                binding="custom",
            )
        )
    )

    assert result["status"] == "incompatible"
    assert result["compatible"] is False
    assert result["code"] == "graphrag_model_incompatible"
    assert result["retryable"] is False
    assert "sk-secret-must-not-leak" not in result["message"]


def test_completion_probe_reports_auth_failure_as_unverifiable(monkeypatch) -> None:
    class AuthenticationError(Exception):
        pass

    async def _isolated(_work) -> None:
        raise AuthenticationError("invalid sk-secret-must-not-leak")

    monkeypatch.setattr(engine, "_run_isolated", _isolated)

    result = asyncio.run(
        engine.probe_completion_model(
            _Cfg("candidate-model", "https://api.example.com/v1", "sk-test")
        )
    )

    assert result["status"] == "unverifiable"
    assert result["compatible"] is None
    assert result["code"] == "graphrag_model_authentication_failed"
    assert result["retryable"] is False
    assert "credentials" in result["message"].lower()
    assert "sk-secret-must-not-leak" not in result["message"]


def test_completion_probe_reports_truncated_output_as_unverifiable(monkeypatch) -> None:
    async def _isolated(_work) -> None:
        raise GraphRagStructuredOutputTruncatedError("secret response content")

    monkeypatch.setattr(engine, "_run_isolated", _isolated)

    result = asyncio.run(
        engine.probe_completion_model(
            _Cfg("candidate-model", "https://api.example.com/v1", "sk-test")
        )
    )

    assert result["status"] == "unverifiable"
    assert result["compatible"] is None
    assert result["code"] == "graphrag_model_output_truncated"
    assert result["retryable"] is True
    assert "secret response content" not in result["message"]


@pytest.mark.parametrize(
    ("error_name", "code"),
    [
        ("RateLimitError", "graphrag_model_rate_limited"),
        ("APIConnectionError", "graphrag_model_connection_failed"),
        ("Timeout", "graphrag_model_connection_failed"),
        ("ServiceUnavailableError", "graphrag_model_connection_failed"),
    ],
)
def test_completion_probe_marks_transient_failures_retryable(
    monkeypatch, error_name: str, code: str
) -> None:
    error_type = type(error_name, (Exception,), {})

    async def _isolated(_work) -> None:
        raise error_type("temporary provider failure")

    monkeypatch.setattr(engine, "_run_isolated", _isolated)

    result = asyncio.run(
        engine.probe_completion_model(
            _Cfg("candidate-model", "https://api.example.com/v1", "sk-test")
        )
    )

    assert result["status"] == "unverifiable"
    assert result["compatible"] is None
    assert result["code"] == code
    assert result["retryable"] is True


def test_embedding_preflight_uses_graphrag_client_and_checks_dimension(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _Response:
        first_embedding = [0.1, 0.2, 0.3]

    class _Embedding:
        async def embedding_async(self, **kwargs):
            captured.update(kwargs)
            return _Response()

    monkeypatch.setattr(
        engine,
        "_create_probe_embedding",
        lambda _config: (_Embedding(), 3),
        raising=False,
    )

    asyncio.run(engine._probe_embedding_model_impl(object()))

    assert captured == {
        "input": ["DeepTutor GraphRAG embedding compatibility test"],
        "timeout": 25,
    }


def test_completion_preflight_uses_persisted_settings_client(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    class _CommunityReportResponse:
        pass

    class _Response:
        formatted_response = _CommunityReportResponse()

    class _Completion:
        async def completion_async(self, **kwargs):
            captured.update(kwargs)
            return _Response()

    monkeypatch.setattr(engine, "_load_config", lambda _root: object())
    monkeypatch.setattr(
        engine,
        "_create_configured_probe_completion",
        lambda _config: (_Completion(), _CommunityReportResponse),
    )

    asyncio.run(engine._preflight_completion_impl(tmp_path))

    assert captured["response_format"] is _CommunityReportResponse
    assert captured["stream"] is False


def test_embedding_preflight_reports_dimension_mismatch_without_indexing(monkeypatch) -> None:
    class _Response:
        first_embedding = [0.1, 0.2]

    class _Embedding:
        async def embedding_async(self, **_kwargs):
            return _Response()

    monkeypatch.setattr(
        engine,
        "_create_probe_embedding",
        lambda _config: (_Embedding(), 3),
        raising=False,
    )

    with pytest.raises(GraphRagEmbeddingDimensionError) as exc_info:
        asyncio.run(engine._probe_embedding_model_impl(object()))

    assert exc_info.value.code == "graphrag_embedding_dimension_mismatch"
    assert "returned 2 dimensions" in str(exc_info.value)
    assert "configured for 3" in str(exc_info.value)


def test_embedding_preflight_classifies_endpoint_error_without_leaking_provider_detail(
    monkeypatch,
) -> None:
    class NotFoundError(Exception):
        status_code = 404

    class _Embedding:
        async def embedding_async(self, **_kwargs):
            raise NotFoundError("bad endpoint sk-secret-must-not-leak")

    monkeypatch.setattr(
        engine,
        "_create_probe_embedding",
        lambda _config: (_Embedding(), 3),
        raising=False,
    )

    with pytest.raises(GraphRagEmbeddingEndpointError) as exc_info:
        asyncio.run(engine._probe_embedding_model_impl(object()))

    assert exc_info.value.code == "graphrag_embedding_endpoint_failed"
    assert "embedding model or endpoint was not found" in str(exc_info.value)
    assert "sk-secret-must-not-leak" not in str(exc_info.value)


@pytest.mark.parametrize(
    ("error_name", "status_code", "expected_code", "retryable"),
    [
        ("AuthenticationError", 401, "graphrag_embedding_authentication_failed", False),
        ("RateLimitError", 429, "graphrag_embedding_rate_limited", True),
        ("APIConnectionError", None, "graphrag_embedding_connection_failed", True),
        ("BadRequestError", 400, "graphrag_embedding_incompatible", False),
    ],
)
def test_embedding_error_classification_is_typed_and_secret_free(
    error_name: str,
    status_code: int | None,
    expected_code: str,
    retryable: bool,
) -> None:
    error_type = type(error_name, (Exception,), {"status_code": status_code})

    classified = classify_embedding_error(error_type("sk-secret-must-not-leak"))

    assert classified is not None
    assert classified.code == expected_code
    assert classified.retryable is retryable
    assert "sk-secret-must-not-leak" not in str(classified)


def test_write_settings_roundtrips(tmp_path) -> None:
    import yaml

    path = gr_config.write_settings(
        tmp_path,
        llm_cfg=_Cfg("m", "u", "k"),
        embedding_cfg=_Cfg("e", "u", "k"),
    )
    assert path.exists()
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert "completion_models" in loaded and "embedding_models" in loaded


def test_write_settings_loads_and_builds_cache_via_real_graphrag(tmp_path) -> None:
    """The generated settings.yaml must survive GraphRAG's own config loader and
    cache factory, not just our own yaml.safe_load roundtrip above.

    GraphRAG's loader treats the config text as a ``string.Template`` and
    substitutes env vars into it before parsing YAML, so a literal ``$`` in a
    value (our ``file_pattern`` regex) must be escaped as ``$$`` or
    ``load_config`` raises ``ValueError: Invalid placeholder``. And GraphRAG's
    ``CacheFactory`` only registers ``json``/``memory``/``none`` cache types;
    ``cache.type`` must be ``"json"``, not the ``"file"`` *storage* type.
    This is not installed in CI (see the module docstring), so it is skipped
    there; run locally with the ``graphrag`` extra installed to exercise it.
    """
    pytest.importorskip("graphrag")
    from graphrag.config.load_config import load_config
    from graphrag_cache.cache_factory import create_cache

    gr_config.write_settings(
        tmp_path,
        llm_cfg=_Cfg("m", "u", "k"),
        embedding_cfg=_Cfg("e", "u", "k"),
    )
    config = load_config(root_dir=tmp_path)
    assert config.cache.type == "json"

    cache = create_cache(config.cache)
    assert type(cache).__name__ == "JsonCache"


def test_real_graphrag_model_config_preserves_embedding_request_options(tmp_path) -> None:
    pytest.importorskip("graphrag")

    gr_config.write_settings(
        tmp_path,
        llm_cfg=_Cfg("gpt-4o-mini", "https://chat.test/v1", "sk-llm"),
        embedding_cfg=_Cfg(
            "Qwen/Qwen3-Embedding-8B",
            "https://emb.test/v1/embeddings",
            "sk-emb",
            dim=4096,
            binding="siliconflow",
            extra_headers={"X-Route": "blue"},
        ),
    )

    loaded = engine._load_config(tmp_path)
    model_config = loaded.embedding_models[gr_config.EMBEDDING_MODEL_ID]
    assert model_config.api_base == "https://emb.test/v1"
    assert model_config.call_args == {
        "extra_headers": {"X-Route": "blue"},
        "dimensions": 4096,
    }


@pytest.mark.parametrize(
    "given,expected",
    [
        ("hybrid", "local"),
        ("", "local"),
        (None, "local"),
        ("global", "global"),
        ("DRIFT", "drift"),
        ("basic", "basic"),
        ("nonsense", "local"),
    ],
)
def test_normalize_mode(given, expected) -> None:
    assert gr_config.normalize_mode(given) == expected


def test_is_graphrag_available_reflects_dependency_lookup(monkeypatch) -> None:
    monkeypatch.setattr("importlib.util.find_spec", lambda _name: None)
    assert gr_config.is_graphrag_available() is False


# --------------------------------------------------------------------------- #
# storage
# --------------------------------------------------------------------------- #


def test_storage_meta_and_has_output(tmp_path) -> None:
    root = tmp_path / "version-1"
    assert storage.has_output(root) is False
    storage.write_meta(root)
    meta = json.loads((root / storage.META_FILENAME).read_text(encoding="utf-8"))
    assert meta["provider"] == "graphrag" and meta["signature"] == "graphrag"
    # has_output keys off the parquet artefacts, not the meta marker.
    assert storage.has_output(root) is False
    storage.output_dir(root).mkdir(parents=True, exist_ok=True)
    (storage.output_dir(root) / "entities.parquet").write_bytes(b"")
    assert storage.has_output(root) is True


# --------------------------------------------------------------------------- #
# ingestion
# --------------------------------------------------------------------------- #


def test_ingestion_writes_text_and_skips_noise(tmp_path) -> None:
    root = tmp_path / "root"
    txt = tmp_path / "notes.txt"
    txt.write_text("hello graph world", encoding="utf-8")
    md = tmp_path / "guide.md"
    md.write_text("# Title\nbody", encoding="utf-8")
    empty = tmp_path / "empty.txt"
    empty.write_text("   ", encoding="utf-8")
    img = tmp_path / "pic.png"
    img.write_bytes(b"\x89PNG")

    count = asyncio.run(ingestion.prepare_input([str(txt), str(md), str(empty), str(img)], root))

    assert count == 2
    written = sorted(p.name for p in storage.input_dir(root).glob("*.txt"))
    assert written == ["guide.txt", "notes.txt"]


def test_ingestion_uses_active_parse_service_for_parser_files(tmp_path, monkeypatch) -> None:
    from deeptutor.services import parsing

    root = tmp_path / "root"
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    calls: list[Path] = []

    class _Parsed:
        markdown = "parsed by configured engine"
        blocks: list[dict] = []

    class _ParseService:
        def parse(self, path: Path):
            calls.append(path)
            return _Parsed()

    monkeypatch.setattr(parsing, "get_parse_service", lambda: _ParseService())

    count = asyncio.run(ingestion.prepare_input([str(pdf)], root))

    assert count == 1
    assert calls == [pdf]
    assert (storage.input_dir(root) / "paper.txt").read_text(encoding="utf-8") == (
        "parsed by configured engine"
    )


def test_ingestion_avoids_name_collisions(tmp_path) -> None:
    root = tmp_path / "root"
    a = tmp_path / "a" / "doc.txt"
    b = tmp_path / "b" / "doc.txt"
    for p in (a, b):
        p.parent.mkdir(parents=True)
        p.write_text("content", encoding="utf-8")

    count = asyncio.run(ingestion.prepare_input([str(a), str(b)], root))
    assert count == 2
    names = sorted(p.name for p in storage.input_dir(root).glob("*.txt"))
    assert names == ["doc.txt", "doc_1.txt"]


# --------------------------------------------------------------------------- #
# pipeline lifecycle (engine stubbed)
# --------------------------------------------------------------------------- #


def _force_available(monkeypatch, available: bool = True) -> None:
    monkeypatch.setattr(gr_config, "is_graphrag_available", lambda: available)


def _stub_build(monkeypatch) -> list[dict]:
    calls: list[dict] = []

    async def fake_build(
        root_dir,
        *,
        is_update=False,
        preflight_embedding_model=True,
    ):
        calls.append(
            {
                "root": str(root_dir),
                "is_update": is_update,
                "preflight_embedding_model": preflight_embedding_model,
            }
        )
        out = storage.output_dir(Path(root_dir))
        out.mkdir(parents=True, exist_ok=True)
        (out / "entities.parquet").write_bytes(b"")

    monkeypatch.setattr(engine, "build", fake_build)

    async def fake_preflight(_root_dir):
        return None

    monkeypatch.setattr(engine, "preflight_completion", fake_preflight, raising=False)
    monkeypatch.setattr(engine, "preflight_embedding", fake_preflight, raising=False)

    # initialize() -> write_settings() resolves the active chat + embedding
    # models from the catalog; CI has none configured, so pin fakes here so the
    # settings.yaml write succeeds. The build_settings <-> catalog bridge itself
    # is covered by the test_build_settings_* tests above.
    monkeypatch.setattr(
        "deeptutor.services.config.resolve_llm_runtime_config",
        lambda: _Cfg("gpt-4o-mini", "https://llm.test/v1", "sk-llm"),
    )
    monkeypatch.setattr(
        "deeptutor.services.embedding.get_embedding_config",
        lambda: _Cfg("emb-model", "https://emb.test/v1", "sk-emb"),
    )
    return calls


def test_incremental_preflight_checks_both_models_before_mutation(monkeypatch) -> None:
    calls: list[str] = []

    async def preflight_embedding(root_dir: Path) -> None:
        assert (root_dir / gr_config.SETTINGS_FILENAME).exists()
        calls.append("embedding")

    async def preflight_completion(root_dir: Path) -> None:
        assert (root_dir / gr_config.SETTINGS_FILENAME).exists()
        calls.append("completion")

    monkeypatch.setattr(engine, "preflight_embedding", preflight_embedding)
    monkeypatch.setattr(engine, "preflight_completion", preflight_completion)

    asyncio.run(GraphRagPipeline()._preflight_settings({"models": {}}))

    assert calls == ["embedding", "completion"]


def test_initialize_requires_graphrag(tmp_path, monkeypatch) -> None:
    _force_available(monkeypatch, False)
    txt = tmp_path / "a.txt"
    txt.write_text("x", encoding="utf-8")
    pipe = GraphRagPipeline(kb_base_dir=str(tmp_path))
    with pytest.raises(gr_config.GraphRagNotAvailableError):
        asyncio.run(pipe.initialize("kb", [str(txt)]))


def test_initialize_orchestrates_index(tmp_path, monkeypatch) -> None:
    _force_available(monkeypatch, True)
    calls = _stub_build(monkeypatch)
    txt = tmp_path / "a.txt"
    txt.write_text("graph content", encoding="utf-8")

    pipe = GraphRagPipeline(kb_base_dir=str(tmp_path))
    ok = asyncio.run(pipe.initialize("kb", [str(txt)]))

    assert ok is True
    assert calls == [
        {
            "root": calls[0]["root"],
            "is_update": False,
            "preflight_embedding_model": True,
        }
    ]
    root = Path(calls[0]["root"])
    assert (root / gr_config.SETTINGS_FILENAME).exists()
    assert list(storage.input_dir(root).glob("*.txt"))
    assert (root / storage.META_FILENAME).exists()


def test_initialize_no_text_returns_false(tmp_path, monkeypatch) -> None:
    _force_available(monkeypatch, True)
    calls = _stub_build(monkeypatch)
    img = tmp_path / "pic.png"
    img.write_bytes(b"\x89PNG")

    pipe = GraphRagPipeline(kb_base_dir=str(tmp_path))
    ok = asyncio.run(pipe.initialize("kb", [str(img)]))

    assert ok is False
    assert calls == []  # build never runs without extractable text


def test_add_documents_runs_update_when_indexed(tmp_path, monkeypatch) -> None:
    _force_available(monkeypatch, True)
    calls = _stub_build(monkeypatch)
    pipe = GraphRagPipeline(kb_base_dir=str(tmp_path))

    a = tmp_path / "a.txt"
    a.write_text("one", encoding="utf-8")
    asyncio.run(pipe.initialize("kb", [str(a)]))

    b = tmp_path / "b.txt"
    b.write_text("two", encoding="utf-8")
    ok = asyncio.run(pipe.add_documents("kb", [str(b)]))

    assert ok is True
    assert calls[-1]["is_update"] is True
    assert calls[-1]["preflight_embedding_model"] is False


def test_add_documents_preflight_failure_does_not_mutate_existing_index(
    tmp_path, monkeypatch
) -> None:
    _force_available(monkeypatch, True)
    _stub_build(monkeypatch)
    pipe = GraphRagPipeline(kb_base_dir=str(tmp_path))

    first = tmp_path / "a.txt"
    first.write_text("existing graph content", encoding="utf-8")
    asyncio.run(pipe.initialize("kb", [str(first)]))

    kb_dir = tmp_path / "kb"
    root = resolve_storage_dir_for_read(kb_dir, None)
    assert root is not None
    settings_before = (root / gr_config.SETTINGS_FILENAME).read_bytes()
    input_before = {
        path.name: path.read_bytes() for path in sorted(storage.input_dir(root).glob("*.txt"))
    }

    async def fail_preflight(_settings) -> None:
        raise GraphRagEmbeddingEndpointError(
            "The configured GraphRAG embedding model or endpoint was not found."
        )

    monkeypatch.setattr(pipe, "_preflight_settings", fail_preflight, raising=False)
    second = tmp_path / "b.txt"
    second.write_text("new graph content", encoding="utf-8")

    with pytest.raises(GraphRagEmbeddingEndpointError):
        asyncio.run(pipe.add_documents("kb", [str(second)]))

    assert (root / gr_config.SETTINGS_FILENAME).read_bytes() == settings_before
    assert {
        path.name: path.read_bytes() for path in sorted(storage.input_dir(root).glob("*.txt"))
    } == input_before


def test_search_needs_reindex_without_output(tmp_path) -> None:
    res = asyncio.run(GraphRagPipeline(kb_base_dir=str(tmp_path)).search("q", "missing"))
    assert res["needs_reindex"] is True
    assert res["provider"] == "graphrag"
    assert res["sources"] == []


def test_search_not_configured_when_unavailable(tmp_path, monkeypatch) -> None:
    # Index exists on disk, but the package is gone (e.g. uninstalled).
    _force_available(monkeypatch, True)
    _stub_build(monkeypatch)
    txt = tmp_path / "a.txt"
    txt.write_text("content", encoding="utf-8")
    pipe = GraphRagPipeline(kb_base_dir=str(tmp_path))
    asyncio.run(pipe.initialize("kb", [str(txt)]))

    _force_available(monkeypatch, False)
    res = asyncio.run(pipe.search("q", "kb"))
    assert res["error_type"] == "not_configured"
    assert res["provider"] == "graphrag"


def test_search_happy_path(tmp_path, monkeypatch) -> None:
    _force_available(monkeypatch, True)
    _stub_build(monkeypatch)
    txt = tmp_path / "a.txt"
    txt.write_text("content", encoding="utf-8")
    pipe = GraphRagPipeline(kb_base_dir=str(tmp_path))
    asyncio.run(pipe.initialize("kb", [str(txt)]))

    seen = {}

    async def fake_search(root_dir, query, mode):
        seen["mode"] = mode
        return "THE ANSWER", {"sources": [{"id": "u1", "text": "grounded ctx"}]}

    monkeypatch.setattr(engine, "search", fake_search)

    res = asyncio.run(pipe.search("what?", "kb"))
    assert res["answer"] == "THE ANSWER"
    assert res["content"] == "THE ANSWER"
    assert res["mode"] == "local"  # default
    assert res["sources"][0]["content"] == "grounded ctx"
    assert res["sources"][0]["chunk_id"] == "u1"


def test_search_mode_from_kb_config(tmp_path, monkeypatch) -> None:
    _force_available(monkeypatch, True)
    _stub_build(monkeypatch)
    txt = tmp_path / "a.txt"
    txt.write_text("content", encoding="utf-8")
    pipe = GraphRagPipeline(kb_base_dir=str(tmp_path))
    asyncio.run(pipe.initialize("kb", [str(txt)]))

    (tmp_path / "kb_config.json").write_text(
        json.dumps({"knowledge_bases": {"kb": {"search_mode": "global"}}}),
        encoding="utf-8",
    )

    async def fake_search(root_dir, query, mode):
        return f"mode={mode}", {}

    monkeypatch.setattr(engine, "search", fake_search)
    res = asyncio.run(pipe.search("q", "kb"))
    assert res["mode"] == "global"


def test_delete_removes_kb_dir(tmp_path, monkeypatch) -> None:
    _force_available(monkeypatch, True)
    _stub_build(monkeypatch)
    txt = tmp_path / "a.txt"
    txt.write_text("content", encoding="utf-8")
    pipe = GraphRagPipeline(kb_base_dir=str(tmp_path))
    asyncio.run(pipe.initialize("kb", [str(txt)]))
    assert (tmp_path / "kb").exists()

    ok = asyncio.run(pipe.delete("kb"))
    assert ok is True
    assert not (tmp_path / "kb").exists()


def test_context_to_sources_prefers_concrete_records() -> None:
    sources = _context_to_sources(
        {
            "sources": [{"id": "u1", "text": "unit text"}],
            "reports": [{"title": "Community 0", "content": "summary"}],
        }
    )
    assert len(sources) == 1
    assert sources[0]["chunk_id"] == "u1"
    assert sources[0]["content"] == "unit text"


# --------------------------------------------------------------------------- #
# knowledge-router gating
# --------------------------------------------------------------------------- #


def test_router_provider_preflight_does_not_require_a_model_probe() -> None:
    from deeptutor.api.routers import knowledge

    assert knowledge._assert_provider_ready("llamaindex") is None


def test_router_blocks_graphrag_when_unavailable(monkeypatch) -> None:
    from fastapi import HTTPException

    from deeptutor.api.routers import knowledge

    monkeypatch.setattr(gr_config, "is_graphrag_available", lambda: False)
    with pytest.raises(HTTPException) as exc:
        knowledge._assert_provider_ready(GRAPHRAG_PROVIDER)
    assert exc.value.status_code == 400


def test_router_graphrag_readiness_does_not_make_a_paid_model_call(monkeypatch) -> None:
    from deeptutor.api.routers import knowledge
    from deeptutor.services.rag import preflight
    from deeptutor.services.rag.pipelines.graphrag import compatibility

    monkeypatch.setattr(gr_config, "is_graphrag_available", lambda: True)
    monkeypatch.setattr(
        preflight,
        "engine_preflight",
        lambda _provider: {"ok": True, "checks": []},
    )

    async def _unexpected_probe() -> dict:
        raise AssertionError("readiness checks must not call the model provider")

    monkeypatch.setattr(
        compatibility,
        "probe_active_completion_model",
        _unexpected_probe,
    )

    assert knowledge._assert_provider_ready(GRAPHRAG_PROVIDER) is None
