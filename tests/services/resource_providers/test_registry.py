"""Registry routing, state persistence, and failure degradation."""

from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.services.config.runtime_settings import RuntimeSettingsService
from deeptutor.services.resource_providers import (
    LookupRequest,
    ProviderManifest,
    ReferenceOfflineDictionaryProvider,
    ResourceProviderRegistry,
    set_provider_enabled,
)
from deeptutor.services.resource_providers.protocol import (
    LOOKUP_DISABLED,
    LOOKUP_ERROR,
    LOOKUP_NOT_FOUND,
    LOOKUP_OK,
)


def _service(tmp_path: Path) -> RuntimeSettingsService:
    return RuntimeSettingsService(tmp_path, process_env={})


def _broken_provider():
    class Broken:
        @property
        def manifest(self):
            return ProviderManifest(
                name="broken", provider_type="dictionary", version="1", languages=("en", "zh")
            )

        async def lookup(self, request):
            raise RuntimeError("boom")

    return Broken()


@pytest.mark.anyio
async def test_lookup_routes_by_language_and_hits_reference(tmp_path: Path) -> None:
    registry = ResourceProviderRegistry()
    registry.register(ReferenceOfflineDictionaryProvider())
    result = await registry.lookup(LookupRequest(term="tokenize"), service=_service(tmp_path))
    assert result.status == LOOKUP_OK


@pytest.mark.anyio
async def test_lookup_no_provider_for_pair_is_not_found(tmp_path: Path) -> None:
    registry = ResourceProviderRegistry()
    result = await registry.lookup(
        LookupRequest(term="x", source_lang="en", target_lang="de"),
        service=_service(tmp_path),
    )
    assert result.status == LOOKUP_NOT_FOUND


@pytest.mark.anyio
async def test_disabled_provider_is_skipped(tmp_path: Path) -> None:
    service = _service(tmp_path)
    registry = ResourceProviderRegistry()
    registry.register(ReferenceOfflineDictionaryProvider())
    set_provider_enabled("reference-offline-dictionary", False, service=service)
    result = await registry.lookup(LookupRequest(term="tokenize"), service=service)
    assert result.status == LOOKUP_DISABLED


@pytest.mark.anyio
async def test_provider_crash_degrades_to_error(tmp_path: Path) -> None:
    service = _service(tmp_path)
    registry = ResourceProviderRegistry()
    registry.register(_broken_provider())
    result = await registry.lookup(LookupRequest(term="anything"), service=service)
    assert result.status == LOOKUP_ERROR
    assert "boom" in result.message


@pytest.mark.anyio
async def test_unknown_named_provider_is_error(tmp_path: Path) -> None:
    registry = ResourceProviderRegistry()
    result = await registry.lookup(
        LookupRequest(term="x"), provider_name="missing", service=_service(tmp_path)
    )
    assert result.status == LOOKUP_ERROR
    assert "not registered" in result.message
