"""Regression tests for DeepTutor's GraphRAG completion compatibility seam."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import threading

import pytest

from deeptutor.services.rag.pipelines.graphrag import config as gr_config
from deeptutor.services.rag.pipelines.graphrag import engine
from deeptutor.services.rag.pipelines.graphrag.errors import (
    GraphRagStructuredOutputError,
    GraphRagStructuredOutputTruncatedError,
    GraphRagUnsupportedProviderError,
)


class _Cfg:
    def __init__(
        self,
        model: str,
        url: str,
        key: str,
        *,
        binding: str = "openai",
        dim: int = 3072,
        reasoning_effort: str | None = None,
    ) -> None:
        self.model = model
        self.effective_url = url
        self.base_url = None
        self.api_key = key
        self.api_version = None
        self.extra_headers: dict[str, str] = {}
        self.binding = binding
        self.provider_name = binding
        self.reasoning_effort = reasoning_effort
        self.dim = dim


def _load_completion(
    tmp_path: Path,
    *,
    binding: str = "deepseek",
    model: str = "deepseek-v4-flash",
    url: str = "https://api.deepseek.com",
):
    from graphrag_llm.completion import create_completion

    gr_config.write_settings(
        tmp_path,
        llm_cfg=_Cfg(
            model,
            url,
            "sk-test",
            binding=binding,
        ),
        embedding_cfg=_Cfg("embedding-model", "https://embedding.test/v1", "sk-test"),
    )
    loaded = engine._load_config(tmp_path)
    return create_completion(loaded.get_completion_model_config(gr_config.COMPLETION_MODEL_ID))


def _report_payload() -> dict:
    return {
        "title": "Compatibility",
        "summary": "The adapter returned structured output.",
        "findings": [{"summary": "Finding", "explanation": "Validated locally."}],
        "rating": 8,
        "rating_explanation": "The response matched the schema.",
    }


def _model_response(litellm, payload: dict | str, *, finish_reason: str = "stop"):
    content = payload if isinstance(payload, str) else json.dumps(payload)
    return litellm.ModelResponse(
        model="deepseek-v4-flash",
        choices=[
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": finish_reason,
            }
        ],
    )


def test_settings_route_deepseek_completion_without_changing_embedding() -> None:
    settings = gr_config.build_settings(
        llm_cfg=_Cfg(
            "deepseek-v4-flash",
            "https://api.deepseek.com",
            "sk-test",
            binding="deepseek",
        ),
        embedding_cfg=_Cfg(
            "Qwen/Qwen3-Embedding-8B",
            "https://api.siliconflow.cn/v1",
            "sk-test",
            binding="siliconflow",
            dim=4096,
        ),
    )

    completion = settings["completion_models"][gr_config.COMPLETION_MODEL_ID]
    embedding = settings["embedding_models"][gr_config.EMBEDDING_MODEL_ID]
    assert completion["type"] == "deeptutor_litellm"
    assert completion["model_provider"] == "deepseek"
    assert embedding.get("type", "litellm") == "litellm"
    assert embedding["model_provider"] == "openai"


def test_probe_completion_uses_same_reasoning_options_as_persisted_settings() -> None:
    pytest.importorskip("graphrag")
    cfg = _Cfg(
        "deepseek-v4-pro",
        "https://api.deepseek.com",
        "sk-test",
        binding="deepseek",
    )

    completion, _response_model = engine._create_probe_completion(cfg)
    settings = gr_config.build_settings(
        llm_cfg=cfg,
        embedding_cfg=_Cfg("embedding-model", "https://embedding.test/v1", "sk-test"),
    )

    expected = settings["completion_models"][gr_config.COMPLETION_MODEL_ID]["call_args"]
    assert completion._model_config.call_args == expected


def test_real_graphrag_completion_falls_back_when_schema_type_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    litellm = pytest.importorskip("litellm")
    pytest.importorskip("graphrag")
    from graphrag.index.operations.summarize_communities.community_reports_extractor import (
        CommunityReportResponse,
    )

    from deeptutor.services.rag.pipelines.graphrag import completion_adapter

    completion_adapter.clear_capability_cache()
    completion = _load_completion(tmp_path)
    calls: list[dict] = []

    async def _acompletion(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise litellm.BadRequestError(
                message="This response_format type is unavailable now",
                model="deepseek-v4-flash",
                llm_provider="deepseek",
            )
        return _model_response(litellm, _report_payload())

    monkeypatch.setattr(litellm, "acompletion", _acompletion)
    response = asyncio.run(
        completion.completion_async(
            messages="Return one community report.",
            response_format=CommunityReportResponse,
            stream=False,
        )
    )

    assert len(calls) == 2
    assert calls[0]["response_format"] is CommunityReportResponse
    assert calls[1]["response_format"] == {"type": "json_object"}
    assert "json schema" in str(calls[1]["messages"]).lower()
    assert isinstance(response.formatted_response, CommunityReportResponse)


def test_custom_anthropic_endpoint_uses_prompt_only_structured_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    litellm = pytest.importorskip("litellm")
    pytest.importorskip("graphrag")
    from graphrag.index.operations.summarize_communities.community_reports_extractor import (
        CommunityReportResponse,
    )

    completion = _load_completion(
        tmp_path,
        binding="anthropic",
        model="third-party-model",
        url="https://compatible-provider.example/v1",
    )
    calls: list[dict] = []

    async def _acompletion(**kwargs):
        calls.append(kwargs)
        return _model_response(litellm, _report_payload())

    monkeypatch.setattr(litellm, "acompletion", _acompletion)
    response = asyncio.run(
        completion.completion_async(
            messages="Return one community report.",
            response_format=CommunityReportResponse,
            stream=False,
        )
    )

    assert len(calls) == 1
    assert "response_format" not in calls[0]
    assert "json schema" in str(calls[0]["messages"]).lower()
    assert isinstance(response.formatted_response, CommunityReportResponse)


def test_official_anthropic_endpoint_keeps_native_structured_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    litellm = pytest.importorskip("litellm")
    pytest.importorskip("graphrag")
    from graphrag.index.operations.summarize_communities.community_reports_extractor import (
        CommunityReportResponse,
    )

    completion = _load_completion(
        tmp_path,
        binding="anthropic",
        model="claude-compatible-model",
        url="https://api.anthropic.com",
    )
    calls: list[dict] = []

    async def _acompletion(**kwargs):
        calls.append(kwargs)
        return _model_response(litellm, _report_payload())

    monkeypatch.setattr(litellm, "acompletion", _acompletion)
    response = asyncio.run(
        completion.completion_async(
            messages="Return one community report.",
            response_format=CommunityReportResponse,
            stream=False,
        )
    )

    assert len(calls) == 1
    assert calls[0]["response_format"] is CommunityReportResponse
    assert "json schema" not in str(calls[0]["messages"]).lower()
    assert isinstance(response.formatted_response, CommunityReportResponse)


def test_unrelated_bad_request_is_not_retried(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    litellm = pytest.importorskip("litellm")
    pytest.importorskip("graphrag")
    from graphrag.index.operations.summarize_communities.community_reports_extractor import (
        CommunityReportResponse,
    )

    from deeptutor.services.rag.pipelines.graphrag import completion_adapter

    completion_adapter.clear_capability_cache()
    completion = _load_completion(tmp_path)
    calls = 0

    async def _acompletion(**_kwargs):
        nonlocal calls
        calls += 1
        raise litellm.BadRequestError(
            message="Invalid temperature",
            model="deepseek-v4-flash",
            llm_provider="deepseek",
        )

    monkeypatch.setattr(litellm, "acompletion", _acompletion)
    with pytest.raises(litellm.BadRequestError, match="Invalid temperature"):
        asyncio.run(
            completion.completion_async(
                messages="Return one community report.",
                response_format=CommunityReportResponse,
                stream=False,
            )
        )

    assert calls == 1


def test_sync_completion_caches_explicit_json_object_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    litellm = pytest.importorskip("litellm")
    pytest.importorskip("graphrag")
    from graphrag.index.operations.summarize_communities.community_reports_extractor import (
        CommunityReportResponse,
    )

    from deeptutor.services.rag.pipelines.graphrag import completion_adapter

    completion_adapter.clear_capability_cache()
    completion = _load_completion(tmp_path)
    calls: list[dict] = []

    def _completion(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise litellm.BadRequestError(
                message="This response_format type is unavailable now",
                model="deepseek-v4-flash",
                llm_provider="deepseek",
            )
        return _model_response(litellm, _report_payload())

    monkeypatch.setattr(litellm, "completion", _completion)
    for _ in range(2):
        response = completion.completion(
            messages="Return one community report.",
            response_format=CommunityReportResponse,
            stream=False,
        )
        assert isinstance(response.formatted_response, CommunityReportResponse)

    assert [call["response_format"] for call in calls] == [
        CommunityReportResponse,
        {"type": "json_object"},
        {"type": "json_object"},
    ]


def test_authentication_failure_is_not_retried(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    litellm = pytest.importorskip("litellm")
    pytest.importorskip("graphrag")
    from graphrag.index.operations.summarize_communities.community_reports_extractor import (
        CommunityReportResponse,
    )

    from deeptutor.services.rag.pipelines.graphrag import completion_adapter

    completion_adapter.clear_capability_cache()
    completion = _load_completion(tmp_path)
    calls = 0

    class AuthenticationError(Exception):
        pass

    async def _acompletion(**_kwargs):
        nonlocal calls
        calls += 1
        raise AuthenticationError("secret provider detail")

    monkeypatch.setattr(litellm, "acompletion", _acompletion)
    with pytest.raises(AuthenticationError):
        asyncio.run(
            completion.completion_async(
                messages="Return one community report.",
                response_format=CommunityReportResponse,
            )
        )
    assert calls == 1


def test_invalid_fallback_json_fails_strict_validation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    litellm = pytest.importorskip("litellm")
    pytest.importorskip("graphrag")
    from graphrag.index.operations.summarize_communities.community_reports_extractor import (
        CommunityReportResponse,
    )

    from deeptutor.services.rag.pipelines.graphrag import completion_adapter

    completion_adapter.clear_capability_cache()
    completion = _load_completion(tmp_path)
    calls = 0

    async def _acompletion(**_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise litellm.BadRequestError(
                message="This response_format type is unavailable now",
                model="deepseek-v4-flash",
                llm_provider="deepseek",
            )
        return _model_response(litellm, {"unexpected": "shape"})

    monkeypatch.setattr(litellm, "acompletion", _acompletion)
    with pytest.raises(GraphRagStructuredOutputError):
        asyncio.run(
            completion.completion_async(
                messages="Return one community report.",
                response_format=CommunityReportResponse,
            )
        )
    assert calls == 2


def test_truncated_fallback_is_unverifiable_instead_of_incompatible(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    litellm = pytest.importorskip("litellm")
    pytest.importorskip("graphrag")
    from graphrag.index.operations.summarize_communities.community_reports_extractor import (
        CommunityReportResponse,
    )

    from deeptutor.services.rag.pipelines.graphrag import completion_adapter

    completion_adapter.clear_capability_cache()
    completion = _load_completion(tmp_path)
    calls = 0

    async def _acompletion(**_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise litellm.BadRequestError(
                message="This response_format type is unavailable now",
                model="deepseek-v4-flash",
                llm_provider="deepseek",
            )
        return _model_response(
            litellm,
            '{"title":"Compatibility","summary":"truncated',
            finish_reason="length",
        )

    monkeypatch.setattr(litellm, "acompletion", _acompletion)
    with pytest.raises(GraphRagStructuredOutputTruncatedError) as exc_info:
        asyncio.run(
            completion.completion_async(
                messages="Return one community report.",
                response_format=CommunityReportResponse,
            )
        )

    assert exc_info.value.code == "graphrag_model_output_truncated"
    assert exc_info.value.retryable is True
    assert calls == 2


def test_native_validation_failure_retries_once_without_caching(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    litellm = pytest.importorskip("litellm")
    pytest.importorskip("graphrag")
    from graphrag.index.operations.summarize_communities.community_reports_extractor import (
        CommunityReportResponse,
    )

    from deeptutor.services.rag.pipelines.graphrag import completion_adapter

    completion_adapter.clear_capability_cache()
    completion = _load_completion(tmp_path)
    calls: list[dict] = []

    async def _acompletion(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return _model_response(litellm, {"unexpected": "shape"})
        return _model_response(litellm, _report_payload())

    monkeypatch.setattr(litellm, "acompletion", _acompletion)
    for _ in range(2):
        response = asyncio.run(
            completion.completion_async(
                messages="Return one community report.",
                response_format=CommunityReportResponse,
            )
        )
        assert isinstance(response.formatted_response, CommunityReportResponse)

    assert [call["response_format"] for call in calls] == [
        CommunityReportResponse,
        {"type": "json_object"},
        CommunityReportResponse,
    ]


def test_old_settings_are_adapted_in_memory_without_rewrite(tmp_path: Path) -> None:
    pytest.importorskip("graphrag")
    import yaml

    gr_config.write_settings(
        tmp_path,
        llm_cfg=_Cfg(
            "deepseek-v4-flash",
            "https://api.deepseek.com",
            "sk-test",
            binding="deepseek",
        ),
        embedding_cfg=_Cfg("embedding-model", "https://embedding.test/v1", "sk-test"),
    )
    settings_path = tmp_path / gr_config.SETTINGS_FILENAME
    old_settings = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    completion = old_settings["completion_models"][gr_config.COMPLETION_MODEL_ID]
    completion.pop("type")
    completion["model_provider"] = "openai"
    settings_path.write_text(
        yaml.safe_dump(old_settings, sort_keys=False),
        encoding="utf-8",
    )
    before = settings_path.read_bytes()

    loaded = engine._load_config(tmp_path)
    loaded_completion = loaded.get_completion_model_config(gr_config.COMPLETION_MODEL_ID)

    assert loaded_completion.type == "deeptutor_litellm"
    assert loaded_completion.model_provider == "deepseek"
    assert settings_path.read_bytes() == before


def test_provider_resolution_uses_backend_contracts() -> None:
    from deeptutor.services.rag.pipelines.graphrag.provider import (
        resolve_completion_provider,
    )

    assert resolve_completion_provider(_Cfg("claude", "u", "k", binding="anthropic")) == (
        "anthropic"
    )
    assert resolve_completion_provider(_Cfg("model", "u", "k", binding="custom")) == "openai"
    with pytest.raises(GraphRagUnsupportedProviderError):
        resolve_completion_provider(_Cfg("gpt", "u", "k", binding="openai_codex"))


def test_cached_fallback_is_safe_under_concurrent_sync_calls(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    litellm = pytest.importorskip("litellm")
    pytest.importorskip("graphrag")
    from graphrag.index.operations.summarize_communities.community_reports_extractor import (
        CommunityReportResponse,
    )

    from deeptutor.services.rag.pipelines.graphrag import completion_adapter

    completion_adapter.clear_capability_cache()
    completion = _load_completion(tmp_path)
    lock = threading.Lock()
    calls: list[dict] = []

    def _completion(**kwargs):
        with lock:
            calls.append(kwargs)
            call_number = len(calls)
        if call_number == 1:
            raise litellm.BadRequestError(
                message="This response_format type is unavailable now",
                model="deepseek-v4-flash",
                llm_provider="deepseek",
            )
        return _model_response(litellm, _report_payload())

    monkeypatch.setattr(litellm, "completion", _completion)
    completion.completion(
        messages="Warm the capability cache.",
        response_format=CommunityReportResponse,
    )

    def _call(_index: int):
        return completion.completion(
            messages="Return one community report.",
            response_format=CommunityReportResponse,
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        responses = list(executor.map(_call, range(8)))

    assert all(isinstance(item.formatted_response, CommunityReportResponse) for item in responses)
    assert len(calls) == 10
    assert all(call["response_format"] == {"type": "json_object"} for call in calls[1:])
