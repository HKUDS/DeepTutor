"""The immersive-reading mode must be resolvable by the orchestrator.

This file exists because of a real failure: the loop capability and its tools
were registered, but the *mode* the composer sends as ``capability`` was not, so
every turn died with "Unknown capability: immersive_reading". The two registries
are separate on purpose — one holds modes the user picks, the other holds
turn-scoped loop capabilities — and nothing previously forced them to agree.
"""

from __future__ import annotations

import pytest

from deeptutor.capabilities.reading import READING_TOOL_NAMES
from deeptutor.capabilities.registry import LOOP_CAPABILITIES, capability_tool_owners
from deeptutor.runtime.bootstrap.builtin_capabilities import BUILTIN_CAPABILITY_CLASSES
from deeptutor.runtime.registry.capability_registry import get_capability_registry


def test_immersive_reading_is_a_resolvable_mode() -> None:
    registry = get_capability_registry()

    capability = registry.get("immersive_reading")

    assert capability is not None, (
        "the composer sends capability='immersive_reading'; without a registered "
        "mode the orchestrator rejects the turn before it starts"
    )
    assert capability.manifest.name == "immersive_reading"


@pytest.mark.parametrize("name", sorted(BUILTIN_CAPABILITY_CLASSES))
def test_every_declared_mode_loads_and_reports_its_own_name(name: str) -> None:
    """A typo in the class path or a mismatched manifest name fails here.

    Both are silent otherwise: the mode simply disappears from the list and the
    only symptom is a rejected turn.
    """
    capability = get_capability_registry().get(name)

    assert capability is not None, f"{name} is declared but does not load"
    assert capability.manifest.name == name


def test_the_reading_mode_and_its_loop_capability_are_both_registered() -> None:
    """The feature needs both halves: the mode routes the turn, the loop
    capability supplies the tools once a document is open."""
    assert get_capability_registry().get("immersive_reading") is not None
    assert any(cap.name == "immersive_reading" for cap in LOOP_CAPABILITIES)


def test_reading_tools_are_attributed_to_the_reading_capability() -> None:
    owners = capability_tool_owners()

    for tool in READING_TOOL_NAMES:
        assert owners.get(tool) == "immersive_reading", (
            f"{tool} must be grouped under its owning capability in the settings UI"
        )


def test_the_mode_declares_the_tools_it_actually_mounts() -> None:
    manifest = get_capability_registry().get("immersive_reading").manifest

    for tool in READING_TOOL_NAMES:
        assert tool in manifest.tools_used
