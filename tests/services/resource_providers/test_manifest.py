"""Provider manifest validation."""

from __future__ import annotations

import pytest

from deeptutor.services.resource_providers import ProviderManifest


def test_manifest_to_payload_shape() -> None:
    manifest = ProviderManifest(
        name="example",
        provider_type="dictionary",
        version="1.0.0",
        languages=("en", "zh"),
        offline=True,
        permissions=(),
        description="demo",
    )
    payload = manifest.to_payload()
    assert payload["name"] == "example"
    assert payload["type"] == "dictionary"
    assert payload["languages"] == ["en", "zh"]
    assert payload["offline"] is True


def test_manifest_rejects_unknown_type() -> None:
    with pytest.raises(ValueError, match="unknown provider type"):
        ProviderManifest(name="x", provider_type="widget", version="1", languages=("en",))


def test_manifest_requires_name_and_version() -> None:
    with pytest.raises(ValueError, match="name"):
        ProviderManifest(name=" ", provider_type="dictionary", version="1", languages=("en",))
    with pytest.raises(ValueError, match="version"):
        ProviderManifest(name="x", provider_type="dictionary", version=" ", languages=("en",))
