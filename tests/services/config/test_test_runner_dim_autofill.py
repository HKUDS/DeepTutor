"""Verify the embedding test-connection behavior.

Contract (post-simplification): the API probe is the single source of truth.

* Every successful probe overwrites the catalog dim with the detected value
  and emits ``active_dim_source = "detected"`` — regardless of what was in
  the catalog before. Matryoshka users who want a truncated variant edit the
  field manually after the test.
* Empty/None vector → still raise.
* The smoke probe always sends ``dim=0`` so the response shows the model's
  native max (Matryoshka models would otherwise truncate to whatever the
  catalog asked for, making "detection" meaningless).
* ``supported_dimensions`` is cached on the active model entry as CSV in the
  same save round-trip.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deeptutor.services.config.test_runner import ConfigTestRunner, TestRun


def _make_run() -> TestRun:
    return TestRun(id="run-1", service="embedding")


def _resolved_stub(dim: int = 0) -> Any:
    cfg = MagicMock()
    cfg.model = "test-model"
    cfg.api_key = "k"
    cfg.base_url = "https://api.example.test/v1/embeddings"
    cfg.effective_url = "https://api.example.test/v1/embeddings"
    cfg.binding = "openai"
    cfg.provider_name = "openai"
    cfg.provider_mode = "standard"
    cfg.api_version = ""
    cfg.extra_headers = {}
    cfg.dimension = dim
    cfg.send_dimensions = None
    cfg.request_timeout = 60
    cfg.batch_size = 10
    cfg.batch_delay = 0.0
    return cfg


@pytest.mark.asyncio
async def test_persist_when_catalog_dim_empty() -> None:
    """Empty catalog → probe value is persisted, source is ``detected``."""
    runner = ConfigTestRunner()
    run = _make_run()
    catalog: dict[str, Any] = {}
    model: dict[str, Any] = {"dimension": ""}

    fake_client = MagicMock()
    fake_client.embed = AsyncMock(return_value=[[0.1] * 1024, [0.2] * 1024])

    with (
        patch(
            "deeptutor.services.config.test_runner.resolve_embedding_runtime_config",
            return_value=_resolved_stub(dim=0),
        ),
        patch("deeptutor.services.embedding.client.EmbeddingClient", return_value=fake_client),
        patch.object(runner, "_persist_embedding_dimension", return_value=catalog) as persist_mock,
    ):
        await runner._test_embedding(run, model, catalog)

    persist_mock.assert_called_once()
    args = persist_mock.call_args.args
    assert args[2] == 1024

    infos = [e for e in run.events if e["type"] == "info"]
    assert any(e.get("active_dim_source") == "detected" for e in infos)


@pytest.mark.asyncio
async def test_overwrite_when_catalog_dim_disagrees_unknown_model() -> None:
    """Catalog dim != probe response, model unknown → still overwrite with the
    probe value. Source is ``detected`` (no warning)."""
    runner = ConfigTestRunner()
    run = _make_run()
    catalog: dict[str, Any] = {}
    model: dict[str, Any] = {"dimension": "3072"}

    fake_client = MagicMock()
    fake_client.embed = AsyncMock(return_value=[[0.5] * 1024, [0.6] * 1024])

    with (
        patch(
            "deeptutor.services.config.test_runner.resolve_embedding_runtime_config",
            return_value=_resolved_stub(dim=3072),
        ),
        patch("deeptutor.services.embedding.client.EmbeddingClient", return_value=fake_client),
        patch.object(runner, "_persist_embedding_dimension", return_value=catalog) as persist_mock,
    ):
        await runner._test_embedding(run, model, catalog)

    persist_mock.assert_called_once()
    args = persist_mock.call_args.args
    assert args[2] == 1024  # detected value, not the prior 3072

    infos = [e for e in run.events if e["type"] == "info"]
    warnings = [e for e in run.events if e["type"] == "warning"]
    assert any(e.get("active_dim_source") == "detected" for e in infos)
    assert not any(e.get("active_dim_source") for e in warnings)


@pytest.mark.asyncio
async def test_non_numeric_catalog_dim_does_not_block_probe() -> None:
    """Bad manual catalog values should not stop the smoke probe from detecting
    and persisting the provider's actual dimension."""
    runner = ConfigTestRunner()
    run = _make_run()
    catalog: dict[str, Any] = {}
    model: dict[str, Any] = {"dimension": "not-a-number"}

    fake_client = MagicMock()
    fake_client.embed = AsyncMock(return_value=[[0.5] * 768, [0.6] * 768])

    with (
        patch(
            "deeptutor.services.config.test_runner.resolve_embedding_runtime_config",
            return_value=_resolved_stub(dim=0),
        ),
        patch("deeptutor.services.embedding.client.EmbeddingClient", return_value=fake_client),
        patch.object(runner, "_persist_embedding_dimension", return_value=catalog) as persist_mock,
    ):
        await runner._test_embedding(run, model, catalog)

    persist_mock.assert_called_once()
    assert persist_mock.call_args.args[2] == 768


@pytest.mark.asyncio
async def test_empty_vector_still_fatal() -> None:
    runner = ConfigTestRunner()
    run = _make_run()
    catalog: dict[str, Any] = {}
    model: dict[str, Any] = {"dimension": ""}

    fake_client = MagicMock()
    fake_client.embed = AsyncMock(return_value=[[], []])

    with (
        patch(
            "deeptutor.services.config.test_runner.resolve_embedding_runtime_config",
            return_value=_resolved_stub(dim=0),
        ),
        patch("deeptutor.services.embedding.client.EmbeddingClient", return_value=fake_client),
    ):
        with pytest.raises(ValueError, match="empty vector"):
            await runner._test_embedding(run, model, catalog)


def _client_with_known_model(
    *,
    model_name: str,
    actual_dim: int,
    default_dim: int,
    supported: list[int],
    supports_variable: bool,
) -> MagicMock:
    """Build a fake EmbeddingClient whose adapter advertises a known model."""
    adapter = MagicMock()
    adapter.MODELS_INFO = {model_name: {"default": default_dim, "dimensions": supported}}
    adapter.get_model_info = MagicMock(
        return_value={
            "model": model_name,
            "dimensions": default_dim,
            "supported_dimensions": supported,
            "supports_variable_dimensions": supports_variable,
        }
    )
    fake_client = MagicMock()
    fake_client.adapter = adapter
    fake_client.embed = AsyncMock(return_value=[[0.0] * actual_dim, [0.1] * actual_dim])
    return fake_client


@pytest.mark.asyncio
async def test_capabilities_event_for_known_model() -> None:
    """When the model is in the adapter's MODELS_INFO, the ``capabilities``
    event reports the supported list and ``model_known=True``, and the
    ``supported_dimensions`` cache is written to the catalog."""
    runner = ConfigTestRunner()
    run = _make_run()
    catalog: dict[str, Any] = {}
    model: dict[str, Any] = {"dimension": ""}

    fake_client = _client_with_known_model(
        model_name="test-model",
        actual_dim=1024,
        default_dim=3072,
        supported=[256, 512, 1024, 3072],
        supports_variable=True,
    )

    with (
        patch(
            "deeptutor.services.config.test_runner.resolve_embedding_runtime_config",
            return_value=_resolved_stub(dim=0),
        ),
        patch("deeptutor.services.embedding.client.EmbeddingClient", return_value=fake_client),
        patch.object(runner, "_persist_embedding_dimension", return_value=catalog),
    ):
        await runner._test_embedding(run, model, catalog)

    caps = [e for e in run.events if e["type"] == "capabilities"]
    assert len(caps) == 1
    payload = caps[0]
    assert payload["detected_dim"] == 1024
    assert payload["default_dim"] == 3072
    assert payload["supported_dimensions"] == [256, 512, 1024, 3072]
    assert payload["supports_variable_dimensions"] is True
    assert payload["model_known"] is True

    # supported_dimensions cached on the model entry as CSV
    assert model.get("supported_dimensions") == "256,512,1024,3072"


@pytest.mark.asyncio
async def test_capabilities_event_for_unknown_model() -> None:
    """When the model is not in MODELS_INFO, ``capabilities`` is still
    emitted but with an empty supported list and ``model_known=False``."""
    runner = ConfigTestRunner()
    run = _make_run()
    catalog: dict[str, Any] = {}
    model: dict[str, Any] = {"dimension": ""}

    adapter = MagicMock()
    adapter.MODELS_INFO = {}  # explicitly empty
    adapter.get_model_info = MagicMock(
        return_value={
            "model": "test-model",
            "dimensions": 0,
            "supports_variable_dimensions": False,
        }
    )
    fake_client = MagicMock()
    fake_client.adapter = adapter
    fake_client.embed = AsyncMock(return_value=[[0.0] * 768, [0.1] * 768])

    with (
        patch(
            "deeptutor.services.config.test_runner.resolve_embedding_runtime_config",
            return_value=_resolved_stub(dim=0),
        ),
        patch("deeptutor.services.embedding.client.EmbeddingClient", return_value=fake_client),
        patch.object(runner, "_persist_embedding_dimension", return_value=catalog),
    ):
        await runner._test_embedding(run, model, catalog)

    caps = [e for e in run.events if e["type"] == "capabilities"]
    assert len(caps) == 1
    payload = caps[0]
    assert payload["detected_dim"] == 768
    assert payload["supported_dimensions"] == []
    assert payload["model_known"] is False
    # No CSV cached when the model is unknown.
    assert model.get("supported_dimensions", "") == ""


@pytest.mark.asyncio
async def test_overwrite_matryoshka_variant_with_native_max() -> None:
    """User had a Matryoshka variant (e.g. 1024d on a 3072d native model) →
    probe overwrites with the native max 3072d. ``supported_dimensions`` cache
    is refreshed in the same save."""
    runner = ConfigTestRunner()
    run = _make_run()
    catalog: dict[str, Any] = {"services": {"embedding": {}}}
    model: dict[str, Any] = {"dimension": "1024", "supported_dimensions": ""}

    fake_client = _client_with_known_model(
        model_name="test-model",
        actual_dim=3072,
        default_dim=3072,
        supported=[256, 512, 1024, 3072],
        supports_variable=True,
    )

    with (
        patch(
            "deeptutor.services.config.test_runner.resolve_embedding_runtime_config",
            return_value=_resolved_stub(dim=1024),
        ),
        patch("deeptutor.services.embedding.client.EmbeddingClient", return_value=fake_client),
        patch.object(runner, "_persist_embedding_dimension", return_value=catalog) as persist,
    ):
        await runner._test_embedding(run, model, catalog)

    persist.assert_called_once()
    args = persist.call_args.args
    assert args[2] == 3072  # detected native max overrides the configured 1024
    assert model["supported_dimensions"] == "256,512,1024,3072"

    infos = [e for e in run.events if e["type"] == "info"]
    assert any(e.get("active_dim_source") == "detected" for e in infos)


@pytest.mark.asyncio
async def test_overwrite_when_dim_out_of_supported_list() -> None:
    """Catalog dim was a value the model doesn't support → probe still
    overwrites with the native max. No warning fired anymore: the probe is
    authoritative."""
    runner = ConfigTestRunner()
    run = _make_run()
    catalog: dict[str, Any] = {"services": {"embedding": {}}}
    model: dict[str, Any] = {"dimension": "999", "supported_dimensions": ""}

    fake_client = _client_with_known_model(
        model_name="test-model",
        actual_dim=3072,
        default_dim=3072,
        supported=[256, 512, 1024, 3072],
        supports_variable=True,
    )

    with (
        patch(
            "deeptutor.services.config.test_runner.resolve_embedding_runtime_config",
            return_value=_resolved_stub(dim=999),
        ),
        patch("deeptutor.services.embedding.client.EmbeddingClient", return_value=fake_client),
        patch.object(runner, "_persist_embedding_dimension", return_value=catalog) as persist,
    ):
        await runner._test_embedding(run, model, catalog)

    persist.assert_called_once()
    assert persist.call_args.args[2] == 3072
    warnings = [e for e in run.events if e["type"] == "warning"]
    infos = [e for e in run.events if e["type"] == "info"]
    assert any(e.get("active_dim_source") == "detected" for e in infos)
    assert not any(e.get("active_dim_source") for e in warnings)


@pytest.mark.asyncio
async def test_smoke_probe_forces_dim_zero() -> None:
    """The smoke probe must construct EmbeddingConfig with ``dim=0`` so the
    request goes out without a ``dimensions=`` parameter — otherwise
    Matryoshka models would just truncate and ``detected_dim`` would echo
    the configured value rather than the model's true native max."""
    runner = ConfigTestRunner()
    run = _make_run()
    catalog: dict[str, Any] = {}
    model: dict[str, Any] = {"dimension": "1024"}

    fake_client = _client_with_known_model(
        model_name="test-model",
        actual_dim=3072,
        default_dim=3072,
        supported=[256, 512, 1024, 3072],
        supports_variable=True,
    )
    captured_configs: list[Any] = []

    def _capture_client(config: Any) -> Any:
        captured_configs.append(config)
        return fake_client

    with (
        patch(
            "deeptutor.services.config.test_runner.resolve_embedding_runtime_config",
            return_value=_resolved_stub(dim=1024),
        ),
        patch(
            "deeptutor.services.embedding.client.EmbeddingClient",
            side_effect=_capture_client,
        ),
        patch.object(runner, "_persist_embedding_dimension", return_value=catalog),
    ):
        await runner._test_embedding(run, model, catalog)

    assert len(captured_configs) == 1
    config = captured_configs[0]
    assert config.dim == 0, "probe must not request a specific dimension"
    assert config.send_dimensions is False
    fake_client.embed.assert_awaited_once()
    assert len(fake_client.embed.await_args.args[0]) == 2


@pytest.mark.asyncio
async def test_capabilities_event_carries_active_dim_source() -> None:
    """The ``capabilities`` SSE payload should include the resolved active
    dim and its source code so the UI can render the badge without waiting
    for a separate event."""
    runner = ConfigTestRunner()
    run = _make_run()
    catalog: dict[str, Any] = {}
    model: dict[str, Any] = {"dimension": ""}

    fake_client = _client_with_known_model(
        model_name="test-model",
        actual_dim=1024,
        default_dim=3072,
        supported=[256, 512, 1024, 3072],
        supports_variable=True,
    )

    with (
        patch(
            "deeptutor.services.config.test_runner.resolve_embedding_runtime_config",
            return_value=_resolved_stub(dim=0),
        ),
        patch("deeptutor.services.embedding.client.EmbeddingClient", return_value=fake_client),
        patch.object(runner, "_persist_embedding_dimension", return_value=catalog),
    ):
        await runner._test_embedding(run, model, catalog)

    caps = [e for e in run.events if e["type"] == "capabilities"]
    assert len(caps) == 1
    payload = caps[0]
    assert payload["active_dim"] == 1024
    assert payload["active_dim_source"] == "detected"
