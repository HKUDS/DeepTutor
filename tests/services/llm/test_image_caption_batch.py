"""Batch alignment, call budgets, and provider-failure boundaries."""

import asyncio
import json

import pytest

from deeptutor.services.llm.exceptions import (
    LLMAPIError,
    LLMAuthenticationError,
    LLMRateLimitError,
    LLMTimeoutError,
    ProviderContextWindowError,
)
from deeptutor.services.llm.image_caption_batch import ImageCaptionBatcher, _decode


def images(count):
    return [
        {"base64": f"data{i}", "mimetype": "image/png", "filename": f"{i}.png"}
        for i in range(count)
    ]


class Client:
    def __init__(self, mode="valid"):
        self.calls = []
        self.mode = mode

    async def complete(self, prompt, **kwargs):
        self.calls.append(kwargs)
        assert kwargs["max_retries"] == 0
        assert kwargs["allow_image_fallback"] is False
        if isinstance(self.mode, BaseException):
            raise self.mode
        if "image_data" in kwargs:
            return "single " + kwargs["image_filename"]
        blocks = kwargs["history"][1]["content"]
        ids = [
            block["text"].split(": ")[1]
            for block in blocks
            if block["type"] == "text" and block["text"].startswith("image_id:")
        ]
        if self.mode == "invalid":
            return "not JSON"
        if self.mode == "overflow" and len(ids) > 2:
            raise ProviderContextWindowError("maximum context")
        return json.dumps(
            {"captions": [{"image_id": key, "caption": key + " caption"} for key in reversed(ids)]}
        )


def batcher(client):
    return ImageCaptionBatcher(client, prompt="Describe each figure", system_prompt="Be factual")


@pytest.mark.asyncio
async def test_single_request_restores_image_order_by_id():
    client = Client()
    assert await batcher(client).describe(images(4)) == [f"IMAGE_{i} caption" for i in range(4)]
    assert len(client.calls) == 1
    assert (
        sum(block["type"] == "image_url" for block in client.calls[0]["history"][1]["content"]) == 4
    )


@pytest.mark.parametrize(
    "response",
    [
        "not json",
        "[]",
        "null",
        '{"captions":[]}',
        '{"captions":[{"image_id":"bad","caption":"x"}]}',
        '{"captions":[{"image_id":"A","caption":"x"},{"image_id":"A","caption":"y"}]}',
        '{"captions":[{"image_id":"A","caption":" "}]}',
    ],
)
def test_invalid_id_maps_are_rejected(response):
    with pytest.raises(ValueError):
        _decode(response, ["A"])


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [2, 3, 4, 8])
async def test_malformed_batches_fall_back_with_bounded_request_tree(count):
    client = Client("invalid")
    assert await batcher(client).describe(images(count)) == [
        f"single {i}.png" for i in range(count)
    ]
    assert len(client.calls) == 2 * count - 1


@pytest.mark.asyncio
async def test_context_overflow_splits_without_discarding_good_smaller_batches():
    client = Client("overflow")
    assert await batcher(client).describe(images(4)) == ["IMAGE_0 caption", "IMAGE_1 caption"] * 2
    assert len(client.calls) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [LLMAuthenticationError(), LLMRateLimitError(), LLMAPIError("forbidden", status_code=403)],
)
async def test_auth_and_rate_errors_stop_queued_batches_without_split(error):
    client = Client(error)
    job = batcher(client)
    assert await job.describe(images(4)) == [None] * 4
    assert await job.describe(images(2)) == [None] * 2
    assert job.halted
    assert len(client.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        LLMTimeoutError(),
        LLMAPIError("service down", status_code=503),
        ValueError("provider error"),
        OSError("connection failed"),
    ],
)
async def test_other_failures_do_not_fan_out(error):
    client = Client(error)
    assert await batcher(client).describe(images(8)) == [None] * 8
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_cancellation_propagates():
    with pytest.raises(asyncio.CancelledError):
        await batcher(Client(asyncio.CancelledError())).describe(images(2))


@pytest.mark.asyncio
async def test_settings_roundtrip_clamps_and_preserves_omitted_fields(tmp_path, monkeypatch):
    from deeptutor.services import config

    monkeypatch.setattr(config, "load_config_with_main", lambda *args, **kwargs: {})
    from deeptutor.api.routers import knowledge
    from deeptutor.services.config.runtime_settings import RuntimeSettingsService
    from deeptutor.services.rag.pipelines.llamaindex import config as rag_config

    service = RuntimeSettingsService(tmp_path / "settings", process_env={})
    monkeypatch.setattr(config, "get_runtime_settings_service", lambda: service)
    monkeypatch.setattr(rag_config, "_load_runtime_settings", service.load_llamaindex)
    assert rag_config.image_description_batch_size() == 1
    await knowledge.update_llamaindex_pipeline_config(
        knowledge.LlamaIndexConfigUpdate(image_description_batch_size=4)
    )
    assert rag_config.image_description_batch_size() == 4
    await knowledge.update_llamaindex_pipeline_config(knowledge.LlamaIndexConfigUpdate(top_k=6))
    assert rag_config.image_description_batch_size() == 4
    await knowledge.update_llamaindex_pipeline_config(
        knowledge.LlamaIndexConfigUpdate(image_description_batch_size=99)
    )
    assert rag_config.image_description_batch_size() == 8
    await knowledge.update_llamaindex_pipeline_config(
        knowledge.LlamaIndexConfigUpdate(image_description_batch_size=0)
    )
    assert rag_config.image_description_batch_size() == 1


@pytest.fixture
def batch_cache(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from deeptutor.services.llm import image_caption_cache

    monkeypatch.setattr(
        image_caption_cache,
        "get_path_service",
        lambda: SimpleNamespace(get_parse_cache_root=lambda: tmp_path),
    )
    return tmp_path


def cached_client(mode="valid"):
    from deeptutor.services.llm.config import LLMConfig

    client = Client(mode)
    client.config = LLMConfig(
        model="vision", api_key="test-secret", base_url="https://example.test/v1"
    )
    return client


@pytest.mark.asyncio
async def test_batch_cache_preserves_request_identity_and_contains_only_captions(batch_cache):
    client = cached_client()
    group = images(2)
    expected = ["IMAGE_0 caption", "IMAGE_1 caption"]
    assert await batcher(client).describe(group) == expected
    assert await batcher(client).describe(group) == expected
    assert len(client.calls) == 1
    for path in batch_cache.rglob("*.json"):
        payload = path.read_text()
        assert json.loads(payload) == {"version": 1, "captions": expected}
        assert not any(
            secret in payload + str(path)
            for secret in ("test-secret", "example.test", "data0", "Be factual")
        )
    await batcher(client).describe(list(reversed(group)))
    client.config.model = "other-vision"
    await batcher(client).describe(group)
    await ImageCaptionBatcher(client, prompt="Read labels", system_prompt="Be factual").describe(
        group
    )
    assert len(client.calls) == 4


@pytest.mark.asyncio
async def test_successful_split_result_is_reused_without_new_provider_requests(batch_cache):
    client = cached_client("invalid")
    expected = [f"single {i}.png" for i in range(4)]
    assert await batcher(client).describe(images(4)) == expected
    assert len(client.calls) == 7
    assert await batcher(client).describe(images(4)) == expected
    assert len(client.calls) == 7


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        LLMAuthenticationError(),
        LLMRateLimitError(),
        LLMAPIError("down", status_code=503),
        asyncio.CancelledError(),
    ],
)
async def test_failed_or_canceled_batch_is_retried_on_next_job(batch_cache, error):
    client = cached_client(error)
    if isinstance(error, asyncio.CancelledError):
        with pytest.raises(asyncio.CancelledError):
            await batcher(client).describe(images(2))
    else:
        assert await batcher(client).describe(images(2)) == [None, None]
    assert not list(batch_cache.rglob("*.json"))
    client.mode = "valid"
    assert await batcher(client).describe(images(2)) == ["IMAGE_0 caption", "IMAGE_1 caption"]
    assert len(client.calls) == 2
