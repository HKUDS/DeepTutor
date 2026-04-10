"""Tests for capability protocol classes."""

from __future__ import annotations

import pytest

from deeptutor.core.capability_protocol import BaseCapability, CapabilityManifest
from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream_bus import StreamBus


def test_capability_manifest_defaults() -> None:
    """CapabilityManifest defaults are safe and empty."""
    manifest_a = CapabilityManifest(name="a", description="a diff")
    manifest_b = CapabilityManifest(name="b", description="b diff")

    manifest_a.stages.append("plan")
    assert len(manifest_b.stages) == 0

    manifest_a.tools_used.append("search")
    assert len(manifest_b.tools_used) == 0

    manifest_a.cli_aliases.append("s")
    assert len(manifest_b.cli_aliases) == 0

    manifest_a.request_schema["prop"] = True
    assert "prop" not in manifest_b.request_schema

    manifest_a.config_defaults["key"] = "val"
    assert "key" not in manifest_b.config_defaults


def test_base_capability_properties() -> None:
    """BaseCapability exposes name and stages from its manifest."""

    class DummyCapability(BaseCapability):
        manifest = CapabilityManifest(
            name="dummy",
            description="Dummy cap",
            stages=["step1", "step2"],
        )

        async def run(self, context: UnifiedContext, stream: StreamBus) -> None:
            pass

    cap = DummyCapability()
    assert cap.name == "dummy"
    assert cap.stages == ["step1", "step2"]


def test_base_capability_is_abstract() -> None:
    """BaseCapability requires run() to be implemented."""

    class IncompleteCapability(BaseCapability):
        manifest = CapabilityManifest(name="incomplete", description="Missing run")

    with pytest.raises(TypeError, match="Can't instantiate abstract class"):
        IncompleteCapability()  # type: ignore
