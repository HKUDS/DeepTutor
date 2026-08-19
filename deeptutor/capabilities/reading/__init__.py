"""Immersive reading loop capability.

``ImmersiveReadingCapability`` (the *mode* the user picks in the composer)
is deliberately NOT re-exported here. It imports the agentic chat pipeline,
which imports the built-in tool registry, which imports this package for
``READING_TOOL_TYPES`` — re-exporting it closes that cycle at interpreter
start. The mode is loaded lazily by class path from
``runtime.bootstrap.builtin_capabilities``, exactly as mastery's is.
"""

from deeptutor.capabilities.reading.capability import (
    MATERIAL_ID_KEY,
    VIEWPORT_KEY,
    ReadingCapability,
    resolve_material_id,
    resolve_viewport,
)
from deeptutor.capabilities.reading.tools import (
    MATERIAL_KWARG,
    READING_TOOL_NAMES,
    READING_TOOL_TYPES,
)

__all__ = [
    "MATERIAL_ID_KEY",
    "MATERIAL_KWARG",
    "READING_TOOL_NAMES",
    "READING_TOOL_TYPES",
    "VIEWPORT_KEY",
    "ReadingCapability",
    "resolve_material_id",
    "resolve_viewport",
]
