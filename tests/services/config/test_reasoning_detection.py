"""Metadata discovery never guesses levels or sends completion requests."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from deeptutor.services.config import reasoning_detection as detection
from deeptutor.services.llm.config import LLMConfig


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [
        ({"reasoning": {"supported_efforts": ["high", "low", "high"]}}, ["low", "high"]),
        ({"supported_reasoning_levels": [{"effort": "medium"}]}, ["medium"]),
        (
            {
                "capabilities": {
                    "effort": {
                        "supported": True,
                        "high": {"supported": True},
                        "max": {"supported": False},
                    }
                }
            },
            ["high"],
        ),
        ({"capabilities": {"effort": {"supported": False}}}, None),
        ({"capabilities": {"effort": {"supported": False}, "thinking": {"supported": False}}}, []),
        ({"supported_reasoning_efforts": []}, []),
        ({"supported_parameters": ["reasoning"]}, None),
        ({"supported_reasoning_efforts": ["invented"]}, ["invented"]),
        ({"supported_reasoning_efforts": "high"}, None),
    ],
)
def test_reads_only_explicit_levels(metadata, expected):
    payload = {"data": [{"id": "vendor/model", **metadata}]}
    assert detection.extract_reasoning_levels(payload, "vendor/model") == expected
    assert detection.extract_reasoning_levels(payload, "model") is None


def test_conflicting_records_remain_unknown():
    assert (
        detection.extract_reasoning_levels(
            {
                "data": [
                    {"id": "m", "supported_reasoning_levels": ["low"]},
                    {"id": "m", "supported_reasoning_levels": ["high"]},
                ]
            },
            "m",
        )
        is None
    )


@pytest.mark.parametrize(
    "model, declared, expected",
    [
        ("qwen3-test", ["low", "medium", "high"], ["high"]),
        ("qwen3-test", ["low", "medium"], []),
        ("qwen3-test", [], []),
        ("qwen3-instruct", ["low", "high"], []),
        ("unknown-model", ["xhigh", "max"], ["xhigh", "max"]),
    ],
)
def test_metadata_is_limited_to_representable_transport_choices(model, declared, expected):
    config = LLMConfig(model=model, binding="custom", api_key="")
    assert detection.compatible_reasoning_levels(config, declared) == expected


def test_single_model_endpoint_can_resolve_alias_but_lists_stay_exact():
    record = {"id": "claude-opus-5-20261101", "supported_reasoning_levels": ["low", "high"]}
    assert detection.extract_reasoning_levels(record, "claude-opus-5-latest") is None
    assert detection.extract_reasoning_levels(
        record, "claude-opus-5-latest", resolved_model=True
    ) == ["low", "high"]
    assert (
        detection.extract_reasoning_levels({"data": [record]}, "different", resolved_model=True)
        is None
    )


def test_future_levels_remain_visible_but_cannot_be_adopted():
    levels = detection.extract_reasoning_levels(
        {"id": "m", "supported_reasoning_levels": ["low", "future"]}, "m"
    )
    assert levels == ["low", "future"]
    assert detection.compatible_reasoning_levels(
        LLMConfig(model="m", api_key="", binding="custom"), levels
    ) == ["low"]


def test_responses_uses_its_own_representable_levels():
    config = LLMConfig(
        model="qwen3-test", api_key="", binding="custom", api_format="openai_responses"
    )
    assert detection.compatible_reasoning_levels(config, ["none", "low", "medium", "high"]) == [
        "low",
        "medium",
        "high",
    ]


def test_native_anthropic_does_not_adopt_off_sentinels_as_effort():
    config = LLMConfig(model="claude-opus-5", api_key="", binding="anthropic")
    assert detection.compatible_reasoning_levels(config, ["none", "minimal", "low", "high"]) == [
        "low",
        "high",
    ]


@pytest.mark.asyncio
async def test_metadata_survives_a_failed_generation_probe(monkeypatch):
    from deeptutor.services.config import loader, test_runner
    from deeptutor.services.llm import factory

    config = LLMConfig(model="m", api_key="", binding="custom")
    monkeypatch.setattr(test_runner, "resolve_llm_runtime_config", lambda **_kwargs: config)
    catalog_service = MagicMock()
    catalog_service.get_active_model.return_value = {}
    monkeypatch.setattr(test_runner, "get_model_catalog_service", lambda: catalog_service)
    monkeypatch.setattr(
        test_runner,
        "detect_reasoning_levels",
        AsyncMock(
            return_value=detection.ReasoningDetection(
                ["high"], "provider_metadata", "now", ["high"]
            )
        ),
    )
    monkeypatch.setattr(loader, "get_agent_params", lambda _name: {})
    monkeypatch.setattr(
        factory, "complete_with_config", AsyncMock(side_effect=ValueError("generation failed"))
    )
    run = test_runner.TestRun(id="failed-probe", service="llm")
    with pytest.raises(ValueError, match="generation failed"):
        await test_runner.ConfigTestRunner()._test_llm(run, catalog={})
    event = next(event for event in run.events if event["type"] == "reasoning_levels")
    assert event["levels"] == ["high"]
    assert event["selectable_levels"] == ["high"]


@pytest.mark.asyncio
async def test_codex_uses_managed_catalog_without_http(monkeypatch):
    http = MagicMock(side_effect=AssertionError("No HTTP request expected"))
    monkeypatch.setattr(detection.aiohttp, "ClientSession", http)
    config = LLMConfig(model="m", api_key="", binding="openai_codex")
    result = await detection.detect_reasoning_levels(
        config, {"codex_supported_reasoning_levels": ["low", "high"]}
    )
    assert result.levels == ["low", "high"]
    assert result.source == "managed_catalog"
    http.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "binding,base_url,model,expected_url",
    [
        ("custom", "https://gateway.test/v1", "m", "https://gateway.test/v1/models"),
        (
            "anthropic",
            "https://gateway.test/v1",
            "claude-opus-4-8",
            "https://gateway.test/v1/models/claude-opus-4-8",
        ),
        (
            "anthropic",
            "https://gateway.test",
            "anthropic/claude-opus-4-8",
            "https://gateway.test/v1/models/claude-opus-4-8",
        ),
        (
            "anthropic",
            "https://gateway.test/proxy/v1/messages",
            "anthropic/claude-opus-4-8",
            "https://gateway.test/proxy/v1/models/claude-opus-4-8",
        ),
    ],
)
@pytest.mark.parametrize(
    "status, body, expected",
    [
        (200, b'{"data":[{"id":"m","reasoning":{"supported_efforts":["low"]}}]}', ["low"]),
        (200, b"{invalid", None),
        (200, b"[" * 1500 + b"0" + b"]" * 1500, None),
        (200, b" " * 2_000_001, None),
        (401, b"", None),
        (403, b"", None),
        (429, b"", None),
        (302, b"", None),
    ],
)
async def test_metadata_request_is_bounded_and_does_not_follow_redirects(
    monkeypatch, status, body, expected, binding, base_url, model, expected_url
):
    async def chunks(_size):
        payload = (
            body.replace(b'"id":"m"', b'"id":"claude-opus-4-8"') if binding == "anthropic" else body
        )
        for index in range(0, len(payload), _size):
            yield payload[index : index + _size]

    response = MagicMock(status=status)
    response.content.iter_chunked = chunks
    response_context = AsyncMock()
    response_context.__aenter__.return_value = response
    session = MagicMock()
    session.get.return_value = response_context
    session_context = AsyncMock()
    session_context.__aenter__.return_value = session
    monkeypatch.setattr(detection.aiohttp, "ClientSession", MagicMock(return_value=session_context))
    config = LLMConfig(
        model=model,
        api_key="test-token",
        binding=binding,
        base_url=base_url,
        extra_headers={"X-Test": "value"},
    )
    result = await detection.detect_reasoning_levels(config)
    assert result.levels == expected
    args, kwargs = session.get.call_args
    assert args == (expected_url,)
    assert kwargs["allow_redirects"] is False
    assert kwargs["headers"]["X-Test"] == "value"
    if binding == "anthropic":
        assert kwargs["headers"]["x-api-key"] == "test-token"
        assert "Authorization" not in kwargs["headers"]
    else:
        assert kwargs["headers"]["Authorization"] == "Bearer test-token"


@pytest.mark.asyncio
async def test_transport_failure_is_unknown(monkeypatch):
    monkeypatch.setattr(
        detection.aiohttp, "ClientSession", MagicMock(side_effect=detection.aiohttp.ClientError())
    )
    result = await detection.detect_reasoning_levels(
        LLMConfig(model="m", api_key="", base_url="https://gateway.test/v1")
    )
    assert result.levels is None
    assert result.source == "unknown"


@pytest.mark.asyncio
async def test_budget_based_anthropic_models_keep_manual_thinking_controls(monkeypatch):
    http = MagicMock(side_effect=AssertionError("No effort metadata request expected"))
    monkeypatch.setattr(detection.aiohttp, "ClientSession", http)
    result = await detection.detect_reasoning_levels(
        LLMConfig(
            model="claude-sonnet-4-5",
            binding="anthropic",
            api_key="",
            base_url="https://provider.test/v1",
        )
    )
    assert result.levels is None
    http.assert_not_called()
