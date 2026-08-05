"""MED-02 adapter-config resolver tests (offline).

The resolver reads the model catalog's ``imagegen`` service and produces a
secret-bearing :class:`AdapterRuntimeConfig` for a durable job, selecting the
adapter kind from the job's protocol and carrying the provider base URL / key /
model.  Tests feed an explicit catalog dict so no settings file is touched.
"""

from __future__ import annotations

import base64
import json
from typing import Any

import httpx
import pytest

from deeptutor.services.media.adapter_config import (
    ADAPTER_MCP,
    ADAPTER_OPENAI_IMAGES,
    ADAPTER_OPENAI_RESPONSES,
    McpImageToolConfig,
)
from deeptutor.services.media.adapters import MediaAdapterRouter
from deeptutor.services.media.config import MediaLimits
from deeptutor.services.media.models import (
    ImageGenerationJob,
    ImageJobStatus,
    MediaConfigError,
)
from deeptutor.services.media.resolver import (
    default_resolver,
    register_mcp_image_tool,
    resolve_runtime_config,
)
from deeptutor.services.media.store import MediaStore
from deeptutor.services.media.worker import ImageGenerationJobWorker
from tests.services.media._media_helpers import make_png


def _catalog(profile: dict[str, Any], *, active_profile_id: str = "p1") -> dict[str, Any]:
    return {
        "version": 1,
        "services": {
            "imagegen": {
                "active_profile_id": active_profile_id,
                "active_model_id": "m1",
                "profiles": [profile],
            }
        },
    }


def _profile(**overrides: Any) -> dict[str, Any]:
    base = {
        "id": "p1",
        "binding": "openai",
        "base_url": "",
        "api_key": "sk-catalog-secret",
        "models": [{"id": "m1", "model": "gpt-image-2", "size": "1024x1024", "quality": "high"}],
    }
    base.update(overrides)
    return base


def _job(*, profile: str = "p1", protocol: str = "", model: str = "") -> ImageGenerationJob:
    return ImageGenerationJob(
        id="j1",
        user_id="u1",
        original_prompt="a red fox",
        request_hash="h",
        profile=profile,
        protocol=protocol,
        model=model,
    )


def test_resolver_defaults_to_images_api() -> None:
    config = resolve_runtime_config(
        _job(protocol="openai_images", model="m1"), catalog=_catalog(_profile())
    )
    assert config.adapter_kind == ADAPTER_OPENAI_IMAGES
    assert config.model == "gpt-image-2"
    assert config.base_url == "https://api.openai.com/v1"
    assert config.api_key == "sk-catalog-secret"
    assert config.size == "1024x1024"
    assert config.quality == "high"
    assert config.supports_edit is True
    assert config.supports_background is False


def test_resolver_selects_responses_protocol() -> None:
    config = resolve_runtime_config(
        _job(protocol="openai_responses", model="m1"), catalog=_catalog(_profile())
    )
    assert config.adapter_kind == ADAPTER_OPENAI_RESPONSES
    assert config.supports_background is True
    assert config.supports_continuation is True
    assert config.supports_edit is False


def test_resolver_selects_mcp_with_registered_tool_mapping() -> None:
    register_mcp_image_tool(
        "mcp-img",
        McpImageToolConfig(
            server_name="images",
            tool_name="make",
            prompt_arg="prompt",
            source_arg="source",
        ),
    )
    try:
        config = resolve_runtime_config(
            _job(profile="mcp-img", protocol="mcp"),
            catalog=_catalog(_profile(id="mcp-img"), active_profile_id="mcp-img"),
        )
        assert config.adapter_kind == ADAPTER_MCP
        assert config.mcp is not None
        assert config.mcp.server_name == "images"
        assert config.mcp.supports_edit is True
        assert config.supports_background is False
    finally:
        from deeptutor.services.media.resolver import _MCP_IMAGE_TOOLS

        _MCP_IMAGE_TOOLS.pop("mcp-img", None)


def test_resolver_mcp_edit_support_follows_tool_config() -> None:
    register_mcp_image_tool(
        "mcp-img",
        McpImageToolConfig(server_name="images", tool_name="make", prompt_arg="prompt"),
    )
    try:
        config = resolve_runtime_config(
            _job(profile="mcp-img", protocol="mcp"),
            catalog=_catalog(_profile(id="mcp-img"), active_profile_id="mcp-img"),
        )
        assert config.adapter_kind == ADAPTER_MCP
        assert config.supports_edit is False
    finally:
        from deeptutor.services.media.resolver import _MCP_IMAGE_TOOLS

        _MCP_IMAGE_TOOLS.pop("mcp-img", None)


def test_resolver_prefers_explicit_job_model() -> None:
    profile = _profile(
        models=[
            {"id": "m1", "model": "gpt-image-2"},
            {"id": "m2", "model": "gpt-image-2-alt"},
        ]
    )
    config = resolve_runtime_config(
        _job(protocol="openai_images", model="m2"),
        catalog=_catalog(profile),
    )
    assert config.model == "gpt-image-2-alt"


def test_resolver_fails_closed_when_profile_missing() -> None:
    """A queued job naming a deleted profile must never silently fall back to
    the active profile or the first configured entry (§11.3)."""
    with pytest.raises(MediaConfigError, match="no longer exists"):
        resolve_runtime_config(
            _job(profile="deleted", protocol="openai_images", model="m1"),
            catalog=_catalog(_profile()),
        )


def test_resolver_fails_closed_when_job_names_no_profile() -> None:
    """A job without an explicit profile cannot guess a provider."""
    with pytest.raises(MediaConfigError, match="does not name a profile"):
        resolve_runtime_config(
            _job(profile="", protocol="openai_images", model="m1"),
            catalog=_catalog(_profile()),
        )


def test_resolver_fails_closed_when_model_missing() -> None:
    """A queued job naming a deleted model must not fall back to the active or
    first configured model (§11.3)."""
    with pytest.raises(MediaConfigError, match="no longer exists"):
        resolve_runtime_config(
            _job(protocol="openai_images", model="deleted-model"),
            catalog=_catalog(_profile()),
        )


def test_resolver_fails_closed_when_job_names_no_model() -> None:
    """A non-MCP job without an explicit model cannot guess a model."""
    with pytest.raises(MediaConfigError, match="does not name a model"):
        resolve_runtime_config(
            _job(protocol="openai_images", model=""),
            catalog=_catalog(_profile()),
        )


def test_resolver_carries_extra_headers_and_auth_style() -> None:
    profile = _profile(
        binding="azure_openai",
        extra_headers={"X-Tenant": "t1"},
        api_version="2024-01-01",
    )
    config = resolve_runtime_config(
        _job(protocol="openai_images", model="m1"), catalog=_catalog(profile)
    )
    assert config.auth_style == "api_key_header"
    assert config.extra_headers == {"X-Tenant": "t1"}
    assert config.api_version == "2024-01-01"


@pytest.mark.asyncio
async def test_router_fails_closed_without_provider_call(tmp_path) -> None:
    """A queued job whose profile was deleted from the catalog fails closed at
    execution time; no adapter/provider call is ever made (§11.3)."""
    store = MediaStore(root=tmp_path / "media", limits=MediaLimits())

    def resolver(job: ImageGenerationJob) -> Any:
        raise MediaConfigError(f"image profile {job.profile!r} no longer exists")

    router = MediaAdapterRouter(store=store, resolver=resolver)
    worker = ImageGenerationJobWorker(store=store)
    worker.set_executor(router)
    job = worker.create_job(
        user_id="u1",
        prompt="a red fox",
        profile="deleted",
        protocol="openai_images",
        model="m1",
    )

    result = await worker.run_job(job.id)

    assert result.status == ImageJobStatus.FAILED
    assert result.error_code == "config_error"
    # No artifacts, references or files were created.
    assert store.list_artifacts(user_id="u1") == []
    assert store.list_references() == []


# ── fail-closed protocol/model resolution (§16.3) ────────────────────────────


def test_resolver_rejects_unknown_explicit_protocol() -> None:
    """An explicit image protocol outside the documented routes (a typo or an
    LLM protocol) must fail closed — it must never silently call the Images
    wire contract (§16.3)."""
    for protocol in ("openai_chat_completions", "typo_responses", "anthropic_messages"):
        with pytest.raises(MediaConfigError, match="unsupported image protocol"):
            resolve_runtime_config(
                _job(protocol=protocol, model="m1"),
                catalog=_catalog(_profile()),
            )


def test_resolver_accepts_explicit_images_and_legacy_protocols() -> None:
    """``openai_responses``, ``mcp`` and ``openai_images`` are documented image
    routes; an empty protocol keeps the legacy profile-based Images mapping."""
    assert (
        resolve_runtime_config(
            _job(protocol="openai_images", model="m1"), catalog=_catalog(_profile())
        ).adapter_kind
        == ADAPTER_OPENAI_IMAGES
    )
    assert (
        resolve_runtime_config(
            _job(protocol="openai_responses", model="m1"), catalog=_catalog(_profile())
        ).adapter_kind
        == ADAPTER_OPENAI_RESPONSES
    )
    assert (
        resolve_runtime_config(
            _job(protocol="", model="m1"), catalog=_catalog(_profile())
        ).adapter_kind
        == ADAPTER_OPENAI_IMAGES
    )


def test_resolver_fails_closed_when_model_entry_has_no_provider_model() -> None:
    """A non-MCP model entry that resolves to an empty provider model fails
    closed — the catalog id must never be sent to the provider (§11.3/§16.3)."""
    profile = _profile(models=[{"id": "m1", "size": "1024x1024"}])
    with pytest.raises(MediaConfigError, match="no provider model"):
        resolve_runtime_config(
            _job(protocol="openai_images", model="m1"),
            catalog=_catalog(profile),
        )


# ── router adapter selection on every boundary (§16.3) ───────────────────────


def _png_b64() -> str:
    return base64.b64encode(make_png(8, 8)).decode("ascii")


def _images_handler(requests: list[httpx.Request]):
    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"created": 1, "data": [{"b64_json": _png_b64()}]})

    return handler


def _images_router(
    store: MediaStore,
    catalog: dict[str, Any],
    requests: list[httpx.Request],
) -> tuple[MediaAdapterRouter, httpx.AsyncClient]:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(_images_handler(requests)),
        follow_redirects=False,
    )
    router = MediaAdapterRouter(
        store=store,
        resolver=default_resolver(catalog),
        http_client=client,
    )
    return router, client


@pytest.mark.asyncio
async def test_router_unsupported_explicit_protocol_fails_closed_without_provider_call(
    tmp_path,
) -> None:
    """A job with an unsupported explicit image protocol fails closed at
    execution time before any provider call (§16.3)."""
    store = MediaStore(root=tmp_path / "media", limits=MediaLimits())
    requests: list[httpx.Request] = []
    router, client = _images_router(store, _catalog(_profile()), requests)
    worker = ImageGenerationJobWorker(store=store)
    worker.set_executor(router)
    job = worker.create_job(
        user_id="u1",
        prompt="a red fox",
        profile="p1",
        protocol="typo_responses",
        model="m1",
        session_id="s1",
    )

    result = await worker.run_job(job.id)

    assert result.status == ImageJobStatus.FAILED
    assert result.error_code == "config_error"
    assert requests == [], "an unsupported protocol must never reach a provider call"
    await router.aclose()
    await client.aclose()


@pytest.mark.asyncio
async def test_router_two_jobs_same_profile_different_models_send_resolved_models(
    tmp_path,
) -> None:
    """Two queued jobs on one profile with different catalog model ids must not
    reuse the first adapter: each POST carries its own resolved provider model,
    never the catalog entry id (§16.3)."""
    catalog = _catalog(
        _profile(
            models=[
                {"id": "m1", "model": "gpt-image-2"},
                {"id": "m2", "model": "gpt-image-2-alt"},
            ]
        )
    )
    store = MediaStore(root=tmp_path / "media", limits=MediaLimits())
    requests: list[httpx.Request] = []
    router, client = _images_router(store, catalog, requests)
    worker = ImageGenerationJobWorker(store=store)
    worker.set_executor(router)
    job1 = worker.create_job(
        user_id="u1",
        prompt="a red fox",
        profile="p1",
        protocol="openai_images",
        model="m1",
        session_id="s1",
    )
    job2 = worker.create_job(
        user_id="u1",
        prompt="a blue bear",
        profile="p1",
        protocol="openai_images",
        model="m2",
        session_id="s2",
    )

    r1 = await worker.run_job(job1.id)
    r2 = await worker.run_job(job2.id)

    assert r1.status == ImageJobStatus.SUCCEEDED
    assert r2.status == ImageJobStatus.SUCCEEDED
    bodies = [json.loads(request.content) for request in requests]
    assert [body["model"] for body in bodies] == ["gpt-image-2", "gpt-image-2-alt"]
    # The router built one adapter per distinct resolved config — no reuse.
    assert len(router._adapters) == 2
    await router.aclose()
    await client.aclose()


@pytest.mark.asyncio
async def test_router_removed_model_fails_closed_before_second_provider_call(
    tmp_path,
) -> None:
    """Deleting the exact model from the catalog after a successful resolution
    fails closed on the next job *before* any second provider call (§11.3)."""
    catalog = _catalog(_profile(models=[{"id": "m1", "model": "gpt-image-2"}]))
    store = MediaStore(root=tmp_path / "media", limits=MediaLimits())
    requests: list[httpx.Request] = []
    router, client = _images_router(store, catalog, requests)
    worker = ImageGenerationJobWorker(store=store)
    worker.set_executor(router)
    job1 = worker.create_job(
        user_id="u1",
        prompt="a red fox",
        profile="p1",
        protocol="openai_images",
        model="m1",
        session_id="s1",
    )
    r1 = await worker.run_job(job1.id)
    assert r1.status == ImageJobStatus.SUCCEEDED
    assert len(requests) == 1

    # Catalog edit: the exact model no longer exists on the profile.
    catalog["services"]["imagegen"]["profiles"][0]["models"] = []
    job2 = worker.create_job(
        user_id="u1",
        prompt="a blue bear",
        profile="p1",
        protocol="openai_images",
        model="m1",
        session_id="s2",
    )
    r2 = await worker.run_job(job2.id)

    assert r2.status == ImageJobStatus.FAILED
    assert r2.error_code == "config_error"
    assert len(requests) == 1, "a deleted model must never reach a provider call"
    await router.aclose()
    await client.aclose()


@pytest.mark.asyncio
async def test_router_removed_profile_fails_closed_before_second_provider_call(
    tmp_path,
) -> None:
    """Deleting the profile from the catalog after a successful resolution
    fails closed on the next job before any second provider call (§11.3)."""
    catalog = _catalog(_profile(models=[{"id": "m1", "model": "gpt-image-2"}]))
    store = MediaStore(root=tmp_path / "media", limits=MediaLimits())
    requests: list[httpx.Request] = []
    router, client = _images_router(store, catalog, requests)
    worker = ImageGenerationJobWorker(store=store)
    worker.set_executor(router)
    job1 = worker.create_job(
        user_id="u1",
        prompt="a red fox",
        profile="p1",
        protocol="openai_images",
        model="m1",
        session_id="s1",
    )
    r1 = await worker.run_job(job1.id)
    assert r1.status == ImageJobStatus.SUCCEEDED
    assert len(requests) == 1

    # Catalog edit: the whole profile is removed.
    catalog["services"]["imagegen"]["profiles"] = []
    job2 = worker.create_job(
        user_id="u1",
        prompt="a blue bear",
        profile="p1",
        protocol="openai_images",
        model="m1",
        session_id="s2",
    )
    r2 = await worker.run_job(job2.id)

    assert r2.status == ImageJobStatus.FAILED
    assert r2.error_code == "config_error"
    assert len(requests) == 1, "a deleted profile must never reach a provider call"
    await router.aclose()
    await client.aclose()


@pytest.mark.asyncio
async def test_router_base_url_change_builds_new_adapter_not_stale(tmp_path) -> None:
    """Changing a profile's endpoint after a successful resolution must build a
    fresh adapter for the new base URL — the old adapter must never be reused."""
    catalog = _catalog(_profile(models=[{"id": "m1", "model": "gpt-image-2"}]))
    store = MediaStore(root=tmp_path / "media", limits=MediaLimits())
    requests: list[httpx.Request] = []
    router, client = _images_router(store, catalog, requests)
    worker = ImageGenerationJobWorker(store=store)
    worker.set_executor(router)
    job1 = worker.create_job(
        user_id="u1",
        prompt="a red fox",
        profile="p1",
        protocol="openai_images",
        model="m1",
        session_id="s1",
    )
    r1 = await worker.run_job(job1.id)
    assert r1.status == ImageJobStatus.SUCCEEDED
    assert str(requests[0].url) == "https://api.openai.com/v1/images/generations"

    # Catalog edit: the profile's endpoint changes.
    catalog["services"]["imagegen"]["profiles"][0]["base_url"] = "https://proxy.example.com/v1"
    job2 = worker.create_job(
        user_id="u1",
        prompt="a blue bear",
        profile="p1",
        protocol="openai_images",
        model="m1",
        session_id="s2",
    )
    r2 = await worker.run_job(job2.id)

    assert r2.status == ImageJobStatus.SUCCEEDED
    assert len(requests) == 2
    assert str(requests[1].url) == "https://proxy.example.com/v1/images/generations"
    assert len(router._adapters) == 2
    await router.aclose()
    await client.aclose()


# ── router-level Responses adapter (resolved provider model, §10.3) ──────────


class _RecordingResponsesTransport:
    """In-memory stand-in for ``_MediaHttpTransport`` that records every
    request; each adapter instance owns one transport, mirroring production."""

    instances: list["_RecordingResponsesTransport"] = []

    def __init__(self, base_url: str, *, connect: int, read: int) -> None:
        self.base_url = base_url
        self.requests: list[dict[str, Any]] = []
        _RecordingResponsesTransport.instances.append(self)

    async def request_json(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        self.requests.append(
            {
                "method": method,
                "path": path,
                "body": body,
                "headers": dict(headers or {}),
            }
        )
        if method == "POST" and path == "/v1/responses":
            return {
                "id": f"resp_{len(self.requests)}",
                "model": "gpt-image-2",
                "status": "in_progress",
                "output": [],
            }
        raise AssertionError(f"unexpected {method} {path} in recording transport")

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_router_responses_two_jobs_send_resolved_provider_models(
    tmp_path,
    monkeypatch,
) -> None:
    """End-to-end router dispatch: two Responses jobs on one profile with
    different catalog model ids each send their own resolved provider model,
    never the catalog entry id."""
    monkeypatch.setattr(
        "deeptutor.services.media.adapters.openai_responses._MediaHttpTransport",
        _RecordingResponsesTransport,
    )
    _RecordingResponsesTransport.instances.clear()
    catalog = _catalog(
        _profile(
            models=[
                {"id": "m1", "model": "gpt-image-2"},
                {"id": "m2", "model": "gpt-image-2-alt"},
            ]
        )
    )
    store = MediaStore(root=tmp_path / "media", limits=MediaLimits())
    router = MediaAdapterRouter(store=store, resolver=default_resolver(catalog))
    worker = ImageGenerationJobWorker(store=store)
    worker.set_executor(router)
    job1 = worker.create_job(
        user_id="u1",
        prompt="a red fox",
        profile="p1",
        protocol="openai_responses",
        model="m1",
        session_id="s1",
    )
    job2 = worker.create_job(
        user_id="u1",
        prompt="a blue bear",
        profile="p1",
        protocol="openai_responses",
        model="m2",
        session_id="s2",
    )

    r1 = await worker.run_job(job1.id)
    r2 = await worker.run_job(job2.id)

    assert r1.status == ImageJobStatus.POLLING
    assert r2.status == ImageJobStatus.POLLING
    submits = [
        record
        for transport in _RecordingResponsesTransport.instances
        for record in transport.requests
        if record["method"] == "POST" and record["path"] == "/v1/responses"
    ]
    assert [record["body"]["model"] for record in submits] == [
        "gpt-image-2",
        "gpt-image-2-alt",
    ]
    assert len(router._adapters) == 2
    await router.aclose()
