"""Compatibility view of module-owned, import-free capability declarations."""

from __future__ import annotations

from dataclasses import dataclass

from deeptutor.core.capability_protocol import CapabilityManifest
from deeptutor.modules.catalog import manifests


@dataclass(frozen=True, slots=True)
class BuiltinCapabilitySpec:
    class_path: str
    manifest: CapabilityManifest


BUILTIN_CAPABILITY_SPECS = {
    name: BuiltinCapabilitySpec(spec["class_path"], CapabilityManifest(**spec["manifest"]))
    for name, spec in sorted(
        (
            (name, spec)
            for module in manifests().values()
            for name, spec in module["capabilities"].items()
        ),
        key=lambda row: row[1]["order"],
    )
}
BUILTIN_CAPABILITY_CLASSES = {
    name: spec.class_path for name, spec in BUILTIN_CAPABILITY_SPECS.items()
}


def builtin_capability_manifest(name: str) -> CapabilityManifest:
    from dataclasses import replace

    from deeptutor.runtime.request_contracts import get_capability_request_schema

    return replace(
        BUILTIN_CAPABILITY_SPECS[name].manifest, request_schema=get_capability_request_schema(name)
    )


__all__ = [
    "BUILTIN_CAPABILITY_SPECS",
    "BUILTIN_CAPABILITY_CLASSES",
    "BuiltinCapabilitySpec",
    "builtin_capability_manifest",
]
