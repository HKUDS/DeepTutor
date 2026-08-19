"""Setup loop capability — DeepTutor inspecting and changing its own configuration."""

from deeptutor.capabilities.setup.capability import SetupCapability
from deeptutor.capabilities.setup.tools import SETUP_TOOL_NAMES, SETUP_TOOL_TYPES

__all__ = ["SETUP_TOOL_NAMES", "SETUP_TOOL_TYPES", "SetupCapability"]
