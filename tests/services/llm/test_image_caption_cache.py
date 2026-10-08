"""Cache behavior without provider calls or user workspace data."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from deeptutor.services.llm import image_caption_cache as cache
from deeptutor.services.llm.client import LLMClient
from deeptutor.services.llm.config import LLMConfig


class Client:
    def __init__(self) -> None:
        self.config = LLMConfig(
            model="vision-test", api_key="test-secret", base_url="https://example.test/v1"
        )
        self.calls = 0
        self.result = "  visible chart  "
        self.error: BaseException | None = None

    async def complete(self, **kwargs: str) -> str:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.result


@pytest.fixture
def cache_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "parse_cache"
    monkeypatch.setattr(
        cache, "get_path_service", lambda: SimpleNamespace(get_parse_cache_root=lambda: root)
    )
    return root


async def describe(client, **overrides) -> str:
    request = {
        "prompt": "Describe the figure",
        "system_prompt": "Only visible facts",
        "image_data": "cG5nLWJ5dGVz",
        "image_mime_type": "image/png",
        "image_filename": "figure.png",
    }
    request.update(overrides)
    return await cache.complete_image_caption(client, **request)


@pytest.mark.asyncio
async def test_reuses_caption_and_persists_only_derived_text(cache_root):
    client = Client()
    client.config.extra_headers = {"Authorization": "header-secret"}
    assert await describe(client) == "visible chart"
    assert await describe(client) == "visible chart"
    assert client.calls == 1
    entries = list(cache_root.rglob("*.json"))
    assert len(entries) == 1
    assert json.loads(entries[0].read_text()) == {"version": 1, "caption": "visible chart"}
    for secret in ("test-secret", "header-secret", "example.test", "cG5nLWJ5dGVz"):
        assert secret not in entries[0].read_text()
        assert secret not in str(entries[0])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("model", "other-model"),
        ("base_url", "https://other.test"),
        ("effective_url", "https://other.test/v1/responses"),
        ("binding", "anthropic"),
        ("provider_name", "other-provider"),
        ("provider_mode", "other-mode"),
        ("api_version", "new-version"),
        ("api_key", "other-account"),
        ("extra_headers", {"x-routing": "other"}),
        ("wire_api", "responses"),
        ("api_format", "anthropic"),
        ("reasoning_effort", "high"),
        ("max_tokens", 200),
        ("temperature", 0.1),
    ],
)
async def test_model_identity_changes_invalidate(cache_root, field, value):
    client = Client()
    await describe(client)
    setattr(client.config, field, value)
    await describe(client)
    assert client.calls == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("prompt", "Read all text"),
        ("system_prompt", "New instructions"),
        ("image_data", "ZGlmZmVyZW50"),
        ("image_mime_type", "image/jpeg"),
        ("image_filename", "other.png"),
    ],
)
async def test_request_changes_invalidate(cache_root, field, value):
    client = Client()
    await describe(client)
    await describe(client, **{field: value})
    assert client.calls == 2


@pytest.mark.asyncio
async def test_force_refresh_replaces_only_on_success(cache_root):
    client = Client()
    await describe(client)
    client.result = "new chart"
    assert await describe(client, force=True) == "new chart"
    client.error = RuntimeError("provider unavailable")
    with pytest.raises(RuntimeError):
        await describe(client, force=True)
    assert await describe(client) == "new chart"
    assert client.calls == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("result", ["", "  ", None])
async def test_empty_responses_are_not_cached(cache_root, result):
    client = Client()
    client.result = result
    assert await describe(client) == ""
    assert await describe(client) == ""
    assert client.calls == 2
    assert not list(cache_root.rglob("*.json"))


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [RuntimeError("failed"), asyncio.CancelledError()])
async def test_failures_propagate_and_are_not_cached(cache_root, error):
    client = Client()
    client.error = error
    with pytest.raises(type(error)):
        await describe(client)
    assert not list(cache_root.rglob("*.json"))
    client.error = None
    assert await describe(client) == "visible chart"
    assert client.calls == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload", ["broken", "null", "[]", '{"version": 99}', '{"version": 1, "caption": 7}']
)
async def test_corrupt_entries_are_replaced(cache_root, payload):
    client = Client()
    await describe(client)
    entry = next(cache_root.rglob("*.json"))
    entry.write_text(payload)
    assert await describe(client) == "visible chart"
    assert client.calls == 2
    assert json.loads(entry.read_text())["caption"] == "visible chart"


@pytest.mark.asyncio
async def test_write_failure_keeps_successful_caption(cache_root, monkeypatch):
    def fail(*args):
        raise PermissionError("read-only filesystem")

    monkeypatch.setattr(cache, "atomic_write_json", fail)
    client = Client()
    assert await describe(client) == "visible chart"
    assert await describe(client) == "visible chart"
    assert client.calls == 2


@pytest.mark.asyncio
async def test_workspace_switch_does_not_reuse_other_users_caption(cache_root, monkeypatch):
    client = Client()
    await describe(client)
    other = cache_root.parent / "other_user" / "parse_cache"
    monkeypatch.setattr(
        cache, "get_path_service", lambda: SimpleNamespace(get_parse_cache_root=lambda: other)
    )
    await describe(client)
    assert client.calls == 2
    assert len(list(other.rglob("*.json"))) == 1


@pytest.mark.asyncio
async def test_unknown_client_identity_bypasses_cache(cache_root):
    client = Client()
    client.config = SimpleNamespace(model="vision-test")
    await describe(client)
    await describe(client)
    assert client.calls == 2
    assert not list(cache_root.rglob("*.json"))


@pytest.mark.asyncio
async def test_legacy_client_runtime_defaults_invalidate(cache_root, monkeypatch):
    from deeptutor.services.llm import factory

    client = LLMClient(Client().config, configure_env=False)
    runtime = Client().config
    monkeypatch.setattr(cache, "get_llm_config", lambda: runtime)
    calls = []

    async def complete(**kwargs):
        calls.append(kwargs)
        return "chart"

    monkeypatch.setattr(factory, "complete", complete)
    await describe(client)
    await describe(client)
    runtime.wire_api = "responses"
    await describe(client)
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_concurrent_writes_leave_complete_json(cache_root):
    client = Client()
    results = await asyncio.gather(*(describe(client) for _ in range(8)))
    assert results == ["visible chart"] * 8
    entry = next(cache_root.rglob("*.json"))
    assert json.loads(entry.read_text())["caption"] == "visible chart"
    assert len(list(entry.parent.iterdir())) == 1


@pytest.mark.asyncio
async def test_unresolved_workspace_bypasses_without_global_fallback(cache_root, monkeypatch):
    def fail():
        raise RuntimeError("invalid workspace")

    monkeypatch.setattr(cache, "get_path_service", fail)
    client = Client()
    assert await describe(client) == "visible chart"
    assert not list(cache_root.rglob("*.json"))


@pytest.mark.asyncio
async def test_timeout_cancels_provider_without_caching(cache_root, monkeypatch):
    client = Client()
    cancelled = asyncio.Event()

    async def slow(**kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(client, "complete", slow)
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(describe(client), timeout=0.1)
    assert cancelled.is_set()
    assert not list(cache_root.rglob("*.json"))


@pytest.mark.asyncio
async def test_llamaindex_description_reuses_cache_and_preserves_source(cache_root, tmp_path):
    pytest.importorskip("llama_index.core")
    from deeptutor.services.rag.pipelines.llamaindex.document_loader import (
        LlamaIndexDocumentLoader,
    )

    path = tmp_path / "figure.png"
    path.write_bytes(b"source image")
    client = Client()
    loader = LlamaIndexDocumentLoader()
    assert await loader._describe_image(client, path, "cG5n", "image/png") == "visible chart"
    assert await loader._describe_image(client, path, "cG5n", "image/png") == "visible chart"
    assert client.calls == 1
    assert path.read_bytes() == b"source image"
