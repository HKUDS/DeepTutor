"""Import-cheap catalog for DeepTutor's built-in tools.

The runtime registry needs to know which names exist at process boot, but it
does not need the implementation classes until a turn actually mounts one.
Keeping the class paths here prevents registry construction from importing the
entire capability graph (and, historically, depending on a lucky import order
to avoid a cycle).
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib
from typing import Iterator, Sequence

from deeptutor.core.tool_protocol import BaseTool


@dataclass(frozen=True, slots=True)
class BuiltinToolSpec:
    name: str
    class_path: str

    def load_class(self) -> type[BaseTool]:
        module_path, class_name = self.class_path.rsplit(":", 1)
        module = importlib.import_module(module_path)
        tool_type = getattr(module, class_name)
        if not isinstance(tool_type, type) or not issubclass(tool_type, BaseTool):
            raise TypeError(f"Built-in tool {self.name!r} did not resolve to a BaseTool class")
        return tool_type

    def create(self) -> BaseTool:
        tool = self.load_class()()
        if tool.name != self.name:
            raise RuntimeError(
                f"Built-in tool catalog drift: {self.class_path} declares {tool.name!r}, "
                f"expected {self.name!r}"
            )
        return tool


from deeptutor.modules.catalog import manifests

BUILTIN_TOOL_SPECS: tuple[BuiltinToolSpec, ...] = tuple(
    BuiltinToolSpec(name, spec["class_path"])
    for name, spec in sorted(
        ((name, spec) for module in manifests().values() for name, spec in module["tools"].items()),
        key=lambda row: row[1]["order"],
    )
)

BUILTIN_TOOL_NAMES: tuple[str, ...] = tuple(spec.name for spec in BUILTIN_TOOL_SPECS)
PARTNER_BUILTIN_TOOL_NAMES: tuple[str, ...] = (
    "partner_read",
    "partner_memorize",
    "partner_search",
)
BUILTIN_TOOL_SPEC_BY_NAME: dict[str, BuiltinToolSpec] = {
    spec.name: spec for spec in BUILTIN_TOOL_SPECS
}

TOOL_ALIASES: dict[str, tuple[str, dict[str, object]]] = {
    "pdf": ("read_source", {}),
    "rag_hybrid": ("rag", {"mode": "hybrid"}),
    "rag_naive": ("rag", {"mode": "naive"}),
    "rag_search": ("rag", {}),
}

if len(BUILTIN_TOOL_SPEC_BY_NAME) != len(BUILTIN_TOOL_SPECS):
    raise RuntimeError("Duplicate name in the built-in tool catalog")


class LazyBuiltinToolTypes(Sequence[type[BaseTool]]):
    """Compatibility sequence that imports a class only when it is iterated."""

    def __init__(self, specs: tuple[BuiltinToolSpec, ...]) -> None:
        self._specs = specs

    def __len__(self) -> int:
        return len(self._specs)

    def __getitem__(self, index):  # noqa: ANN001, ANN204
        if isinstance(index, slice):
            return tuple(spec.load_class() for spec in self._specs[index])
        return self._specs[index].load_class()

    def __iter__(self) -> Iterator[type[BaseTool]]:
        return (spec.load_class() for spec in self._specs)


__all__ = [
    "BUILTIN_TOOL_NAMES",
    "BUILTIN_TOOL_SPEC_BY_NAME",
    "BUILTIN_TOOL_SPECS",
    "BuiltinToolSpec",
    "LazyBuiltinToolTypes",
    "PARTNER_BUILTIN_TOOL_NAMES",
    "TOOL_ALIASES",
]
