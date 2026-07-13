"""User-tunable parameters for the memory consolidator.

Single source of truth is ``data/user/settings/main.yaml`` under the
``memory:`` subtree. Defaults live here. The frontend ``/settings/memory``
page reads/writes the same subtree via the API.

Decoupled from the algorithm code: every mode picks values up via
:func:`load_memory_settings`, never via module-level constants.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields, is_dataclass
from typing import Any, Literal

from deeptutor.utils.config_manager import ConfigManager

_SETTINGS_KEY = "memory"


@dataclass(frozen=True)
class UpdateSettings:
    l2_budget: int = 20
    l3_budget: int = 10


@dataclass(frozen=True)
class AuditSettings:
    l2_budget: int = 20
    l3_budget: int = 10


@dataclass(frozen=True)
class DedupSettings:
    iterations: int = 3
    auto_after_update: bool = True


@dataclass(frozen=True)
class MergeSettings:
    """No-LLM footnote consolidation (collapse duplicate refs into one footnote each)."""

    auto_after_update: bool = True
    auto_after_audit: bool = True
    auto_after_dedup: bool = True


@dataclass(frozen=True)
class ChunkingSettings:
    overlap_ratio: float = 0.10
    boundary: Literal["paragraph", "sentence"] = "paragraph"
    min_chunk_chars: int = 1000
    max_chunk_chars: int = 64000


@dataclass(frozen=True)
class ReferenceSettings:
    enforce_required: bool = True
    drop_invalid_refs: bool = True


@dataclass(frozen=True)
class MemorySettings:
    update: UpdateSettings = field(default_factory=UpdateSettings)
    audit: AuditSettings = field(default_factory=AuditSettings)
    dedup: DedupSettings = field(default_factory=DedupSettings)
    merge: MergeSettings = field(default_factory=MergeSettings)
    chunking: ChunkingSettings = field(default_factory=ChunkingSettings)
    reference: ReferenceSettings = field(default_factory=ReferenceSettings)


def load_memory_settings() -> MemorySettings:
    """Return the current ``memory:`` subtree merged on top of defaults.

    Missing keys fall back to defaults. Out-of-range numeric values are
    clamped to safe ranges so a malformed YAML never crashes a run.
    """
    raw = ConfigManager().load_config().get(_SETTINGS_KEY) or {}
    return _from_dict(MemorySettings, raw)


def save_memory_settings(payload: dict[str, Any]) -> MemorySettings:
    """Merge ``payload`` into the on-disk ``memory:`` subtree.

    Unknown keys are dropped; values are coerced to the schema's types
    so the YAML never picks up junk. Returns the post-merge settings.
    """
    merged = _from_dict(MemorySettings, payload)
    coerced = asdict(merged)
    ConfigManager().save_config({_SETTINGS_KEY: coerced})
    return merged


def memory_settings_dict() -> dict[str, Any]:
    """Settings as a plain dict — JSON-safe for the API response."""
    return asdict(load_memory_settings())


# ── Coercion + clamping ─────────────────────────────────────────────────


_MIN_BUDGET = 1
_MAX_BUDGET = 200
_MIN_DEDUP_ITER = 1
_MAX_DEDUP_ITER = 20
_MIN_OVERLAP = 0.0
_MAX_OVERLAP = 0.5
_MIN_CHUNK_CHARS = 200
_MAX_CHUNK_CHARS = 64000
_BOUNDARIES = ("paragraph", "sentence")


def _from_dict(cls: type, raw: Any) -> Any:
    """Build a frozen dataclass from a partial dict.

    Strategy: walk fields, if a field is itself a dataclass and the input
    has a matching dict, recurse. Otherwise coerce + clamp. Defaults fill
    any missing field.
    """
    if not is_dataclass(cls):
        raise TypeError(f"{cls!r} is not a dataclass")

    instance_defaults = cls()  # type: ignore[call-arg]
    if not isinstance(raw, dict):
        return instance_defaults

    kwargs: dict[str, Any] = {}
    for f in fields(cls):
        provided = raw.get(f.name)
        default = getattr(instance_defaults, f.name)
        if isinstance(f.type, type) and is_dataclass(f.type):
            kwargs[f.name] = _from_dict(f.type, provided) if provided is not None else default
            continue
        # nested dataclass detection through the actual default type
        if is_dataclass(default):
            kwargs[f.name] = (
                _from_dict(type(default), provided) if provided is not None else default
            )
            continue
        kwargs[f.name] = _coerce_scalar(f.name, provided, default)
    return cls(**kwargs)


def _coerce_scalar(name: str, raw: Any, default: Any) -> Any:
    if raw is None:
        return default
    if isinstance(default, bool):
        return bool(raw)
    if isinstance(default, int):
        try:
            int_value = int(raw)
        except (TypeError, ValueError):
            return default
        return _clamp_int(name, int_value, default)
    if isinstance(default, float):
        try:
            float_value = float(raw)
        except (TypeError, ValueError):
            return default
        return _clamp_float(name, float_value, default)
    if isinstance(default, str):
        str_value = str(raw)
        if name == "boundary" and str_value not in _BOUNDARIES:
            return default
        return str_value
    return raw


def _clamp_int(name: str, value: int, default: int) -> int:
    if name.endswith("budget"):
        return max(_MIN_BUDGET, min(_MAX_BUDGET, value))
    if name == "iterations":
        return max(_MIN_DEDUP_ITER, min(_MAX_DEDUP_ITER, value))
    if name == "min_chunk_chars":
        return max(_MIN_CHUNK_CHARS, min(_MAX_CHUNK_CHARS, value))
    if name == "max_chunk_chars":
        return max(_MIN_CHUNK_CHARS, min(_MAX_CHUNK_CHARS, value))
    return max(0, value)


def _clamp_float(name: str, value: float, default: float) -> float:
    if name == "overlap_ratio":
        return max(_MIN_OVERLAP, min(_MAX_OVERLAP, value))
    return value


__all__ = [
    "AuditSettings",
    "ChunkingSettings",
    "DedupSettings",
    "MemorySettings",
    "MergeSettings",
    "ReferenceSettings",
    "UpdateSettings",
    "load_memory_settings",
    "memory_settings_dict",
    "save_memory_settings",
]
