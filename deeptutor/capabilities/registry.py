"""Factory registry for built-in and external chat-loop extensions."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from functools import cache
import importlib
import inspect
import logging
from typing import Any, cast
import warnings

from deeptutor.capabilities.protocol import LoopExtension
from deeptutor.core.context import UnifiedContext
from deeptutor.core.entry_points import load_entry_point_group
from deeptutor.runtime.capability_catalog import EmptyConfig, get_capability_catalog

logger = logging.getLogger(__name__)

EXTENSIONS_GROUP = "deeptutor.extensions"
LOOP_CAPABILITIES_GROUP = "deeptutor.loop_capabilities"

LoopFactory = Callable[[], LoopExtension]


@dataclass(frozen=True, slots=True)
class LoopCapabilitySpec:
    """Import-free descriptor for a built-in chat-loop extension."""

    name: str
    class_path: str

    def create(self) -> LoopExtension:
        module_path, class_name = self.class_path.rsplit(":", 1)
        factory = getattr(importlib.import_module(module_path), class_name)
        extension = factory()
        if getattr(extension, "name", None) != self.name:
            raise RuntimeError(
                f"Loop capability descriptor drift for {self.class_path}: "
                f"expected {self.name!r}, got {getattr(extension, 'name', None)!r}"
            )
        return cast(LoopExtension, extension)

    def __call__(self) -> LoopExtension:
        return self.create()


BUILTIN_LOOP_CAPABILITY_SPECS: tuple[LoopCapabilitySpec, ...] = (
    LoopCapabilitySpec(
        "ask_questions",
        "deeptutor.capabilities.ask_questions.loop:AskQuestionsLoopCapability",
    ),
    LoopCapabilitySpec("mastery", "deeptutor.capabilities.mastery.loop:MasteryLoopCapability"),
    LoopCapabilitySpec("solve", "deeptutor.capabilities.solve.loop:SolveLoopCapability"),
    LoopCapabilitySpec("obsidian", "deeptutor.capabilities.obsidian.capability:ObsidianCapability"),
    LoopCapabilitySpec(
        "marginnote4",
        "deeptutor.capabilities.marginnote4.capability:MarginNoteCapability",
    ),
    LoopCapabilitySpec(
        "subagent",
        "deeptutor.capabilities.subagent.capability:SubagentCapability",
    ),
    LoopCapabilitySpec("ima", "deeptutor.capabilities.ima.capability:ImaCapability"),
    LoopCapabilitySpec(
        "immersive_reading",
        "deeptutor.capabilities.reading.capability:ReadingCapability",
    ),
    LoopCapabilitySpec(
        "course_study",
        "deeptutor.capabilities.course_study.capability:CourseStudyLoopCapability",
    ),
    LoopCapabilitySpec(
        "immersive_watching",
        "deeptutor.capabilities.watching.capability:WatchingCapability",
    ),
    LoopCapabilitySpec(
        "explore_context",
        "deeptutor.capabilities.explore_context.capability:ExploreContextCapability",
    ),
    LoopCapabilitySpec("setup", "deeptutor.capabilities.setup.capability:SetupCapability"),
    LoopCapabilitySpec(
        "partner_authoring",
        "deeptutor.capabilities.partner_authoring.capability:PartnerAuthoringCapability",
    ),
    LoopCapabilitySpec(
        "partner_group",
        "deeptutor.capabilities.partner_group.capability:PartnerGroupCapability",
    ),
    LoopCapabilitySpec(
        "visualization_generation",
        "deeptutor.visualizers.loop_capability:VisualizationLoopCapability",
    ),
)

# Compatibility surface: the descriptors remain zero-argument callables.
LOOP_EXTENSION_FACTORIES: tuple[LoopFactory, ...] = cast(
    tuple[LoopFactory, ...], BUILTIN_LOOP_CAPABILITY_SPECS
)


def _builtin_loop_extensions() -> tuple[LoopExtension, ...]:
    return tuple(factory() for factory in LOOP_EXTENSION_FACTORIES)


class _LegacyLoopCapabilitiesView(Sequence[LoopExtension]):
    """Deprecated sequence view that never retains extension instances."""

    def __len__(self) -> int:
        return len(LOOP_EXTENSION_FACTORIES)

    def __iter__(self) -> Iterator[LoopExtension]:
        return iter(_builtin_loop_extensions())

    def __getitem__(self, index):  # noqa: ANN001, ANN204
        return _builtin_loop_extensions()[index]


LOOP_CAPABILITIES: Sequence[LoopExtension] = _LegacyLoopCapabilitiesView()


def _coerce_loop_factory(loaded: object) -> tuple[LoopExtension, LoopFactory] | None:
    obj: Any = loaded
    if inspect.isclass(obj):
        factory = obj
        instance = obj()
    elif callable(obj) and getattr(obj, "owned_tools", None) is None:
        produced = obj()
        if inspect.isclass(produced):
            factory = produced
            instance = produced()
        else:
            instance = produced
            factory = type(produced)
    else:
        instance = obj
        factory = type(obj)
    name = getattr(instance, "name", None)
    tools = getattr(instance, "owned_tools", None)
    if not isinstance(name, str) or not name.strip() or tools is None:
        return None
    try:
        tuple(tools)
    except TypeError:
        return None
    if not callable(getattr(instance, "is_active", None)):
        return None
    return cast(LoopExtension, instance), cast(LoopFactory, factory)


@cache
def discover_external_loop_capabilities() -> tuple[tuple[str, LoopFactory], ...]:
    """Discover factory specs from canonical and one-version legacy groups."""

    seen = {spec.name for spec in BUILTIN_LOOP_CAPABILITY_SPECS}

    def _accept(ep_name: str, loaded: object) -> tuple[str, LoopFactory] | None:
        resolved = _coerce_loop_factory(loaded)
        if resolved is None:
            logger.warning("Ignoring loop extension plugin '%s': invalid class or factory", ep_name)
            return None
        extension, factory = resolved
        if extension.name in seen:
            logger.warning(
                "Loop extension plugin '%s' shadowed by built-in or earlier plugin (ignored)",
                extension.name,
            )
            return None
        seen.add(extension.name)
        return extension.name, factory

    canonical = load_entry_point_group(EXTENSIONS_GROUP, _accept, log=logger)
    legacy = load_entry_point_group(LOOP_CAPABILITIES_GROUP, _accept, log=logger)
    if legacy:
        warnings.warn(
            f"{LOOP_CAPABILITIES_GROUP} is deprecated; register under {EXTENSIONS_GROUP}",
            DeprecationWarning,
            stacklevel=2,
        )
    return tuple([*canonical, *legacy])


def _register_loop_entry(name: str, factory: LoopFactory) -> None:
    preview = factory()
    get_capability_catalog().register(
        name=name,
        kind="loop_extension",
        manifest={"name": name, "owned_tools": tuple(preview.owned_tools)},
        factory=factory,
        config_model=EmptyConfig,
        replace=True,
    )


def all_loop_capabilities() -> tuple[LoopExtension, ...]:
    """Create an isolated extension set for the caller's turn."""

    specs: list[tuple[str, LoopFactory]] = []
    specs.extend((spec.name, spec) for spec in BUILTIN_LOOP_CAPABILITY_SPECS)
    specs.extend(discover_external_loop_capabilities())
    for name, factory in specs:
        _register_loop_entry(name, factory)
    catalog = get_capability_catalog()
    return tuple(
        cast(LoopExtension, catalog.create("loop_extension", name)) for name, _factory in specs
    )


def active_loop_capabilities(context: UnifiedContext) -> tuple[LoopExtension, ...]:
    return tuple(extension for extension in all_loop_capabilities() if extension.is_active(context))


def any_exclusive_capability_active(context: UnifiedContext) -> bool:
    return any(
        getattr(extension, "exclusive_tools", False)
        for extension in active_loop_capabilities(context)
    )


def capability_tool_owners() -> dict[str, str]:
    return {
        name: extension.name
        for extension in all_loop_capabilities()
        for name in extension.owned_tools
    }


__all__ = [
    "EXTENSIONS_GROUP",
    "BUILTIN_LOOP_CAPABILITY_SPECS",
    "LOOP_CAPABILITIES",
    "LOOP_CAPABILITIES_GROUP",
    "LOOP_EXTENSION_FACTORIES",
    "active_loop_capabilities",
    "all_loop_capabilities",
    "any_exclusive_capability_active",
    "capability_tool_owners",
    "discover_external_loop_capabilities",
]
