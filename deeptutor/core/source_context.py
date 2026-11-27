"""Serialized context contributed by an optional content application."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SourceContext:
    text: str = ""
    references: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
