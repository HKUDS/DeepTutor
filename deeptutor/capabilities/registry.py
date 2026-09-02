"""Factory registry for built-in and external chat-loop extensions."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from functools import cache
import inspect
import logging
from typing import Any, cast
import warnings

from deeptutor.capabilities.ask_questions import AskQuestionsLoopCapability
from deeptutor.capabilities.course_study import CourseStudyLoopCapability
from deeptutor.capabilities.explore_context import ExploreContextCapability
from deeptutor.capabilities.ima import ImaCapability
from deeptutor.capabilities.marginnote4 import MarginNoteCapability
from deeptutor.capabilities.mastery import MasteryLoopCapability
from deeptutor.capabilities.obsidian import ObsidianCapability
from deeptutor.capabilities.partner_authoring import PartnerAuthoringCapability
from deeptutor.capabilities.partner_group import PartnerGroupCapability
from deeptutor.capabilities.protocol import LoopExtension
from deeptutor.capabilities.reading import ReadingCapability
from deeptutor.capabilities.setup import SetupCapability
from deeptutor.capabilities.solve import SolveLoopCapability
from deeptutor.capabilities.subagent import SubagentCapability
from deeptutor.capabilities.watching import WatchingCapability
from deeptutor.core.context import UnifiedContext
from deeptutor.core.entry_points import load_entry_point_group
from deeptutor.runtime.capability_catalog import EmptyConfig, get_capability_catalog
from deeptutor.visualizers.loop_capability import VisualizationLoopCapability

logger = logging.getLogger(__name__)

EXTENSIONS_GROUP = "deeptutor.extensions"
LOOP_CAPABILITIES_GROUP = "deeptutor.loop_capabilities"

LoopFactory = Callable[[], LoopExtension]

LOOP_EXTENSION_FACTORIES: tuple[LoopFactory, ...] = cast(
    tuple[LoopFactory, ...],
    (
        AskQuestionsLoopCapability,
        MasteryLoopCapability,
        SolveLoopCapability,
        ObsidianCapability,
        MarginNoteCapability,
        SubagentCapability,
        ImaCapability,
        ReadingCapability,
        CourseStudyLoopCapability,
        WatchingCapability,
        ExploreContextCapability,
        SetupCapability,
        PartnerAuthoringCapability,
        PartnerGroupCapability,
        VisualizationLoopCapability,
    ),
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

    seen = {cap.name for cap in _builtin_loop_extensions()}

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
    for factory in LOOP_EXTENSION_FACTORIES:
        preview = factory()
        specs.append((preview.name, factory))
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
    "LOOP_CAPABILITIES",
    "LOOP_CAPABILITIES_GROUP",
    "LOOP_EXTENSION_FACTORIES",
    "active_loop_capabilities",
    "all_loop_capabilities",
    "any_exclusive_capability_active",
    "capability_tool_owners",
    "discover_external_loop_capabilities",
]
